import os
from datetime import date
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, send_file, abort, current_app)
from flask_login import login_required, current_user

from ..extensions import db
from ..models import Project, Window, Pane, Quote, ProjectStatus
import json
from ..services.pricing import calculate_price
from ..services.pdf_quote import generate_quote_pdf

quote_bp = Blueprint('quote', __name__)


# ------------------------------------------------------------------ #
#  POST /projects/<id>/quotes/generate
# ------------------------------------------------------------------ #
@quote_bp.route('/projects/<int:project_id>/quotes/generate', methods=['POST'])
@login_required
def generate(project_id):
    try:
        project = _own_project(project_id)
        windows = project.windows.all()

        if not windows:
            flash('Add at least one window before generating a quote.', 'error')
            return redirect(url_for('projects.detail', project_id=project_id))

        # ---- calculate per-window prices ----------------------------
        window_lines = []
        subtotal = 0.0
        for w in windows:
            panes = w.panes.all()
            price = calculate_price(w, panes, current_user.tenant_id,
                                    design=(json.loads(w.design_json) if getattr(w, "design_json", None) else None))
            window_lines.append({
                'window': w,
                'panes':  panes,
                'price':  price,
            })
            subtotal += price['total']

        subtotal = round(subtotal, 2)
        vat_rate = 0.20
        vat_amt  = round(subtotal * vat_rate, 2)
        total    = round(subtotal + vat_amt, 2)

        # ---- create Quote record ------------------------------------
        quote_number = Quote.generate_number(current_user.tenant_id)
        # find the latest revision for this project, if any
        from sqlalchemy import desc as _desc
        prior = (Quote.query
                 .filter_by(project_id=project.id, tenant_id=current_user.tenant_id)
                 .order_by(_desc(Quote.revision))
                 .first())
        new_revision  = (prior.revision + 1) if prior else 1
        parent_id     = prior.id if prior else None
        quote = Quote(
            project_id      = project.id,
            tenant_id       = current_user.tenant_id,
            quote_number    = quote_number,
            issued_date     = date.today(),
            subtotal        = subtotal,
            vat_rate        = vat_rate,
            total           = total,
            revision        = new_revision,
            parent_quote_id = parent_id,
        )
        db.session.add(quote)
        db.session.flush()   # get quote.id before generating PDF

        # ---- generate PDF -------------------------------------------
        try:
            pdf_bytes = generate_quote_pdf(
                quote       = quote,
                project     = project,
                tenant      = current_user.tenant,
                window_lines= window_lines,
                vat_amt     = vat_amt,
            )
            pdf_dir  = os.path.join(current_app.config['UPLOAD_FOLDER'], 'pdfs')
            os.makedirs(pdf_dir, exist_ok=True)
            pdf_filename = f'quote-{quote.id}-{quote_number}.pdf'
            pdf_path     = os.path.join(pdf_dir, pdf_filename)
            with open(pdf_path, 'wb') as f:
                f.write(pdf_bytes)
            quote.pdf_path = f'pdfs/{pdf_filename}'
            current_app.logger.info('PDF generated: %s (%d bytes)', pdf_path, len(pdf_bytes))
        except Exception as exc:
            current_app.logger.exception('PDF generation failed for quote %s: %s',
                                          quote_number, exc)
            # quote is still created, just without PDF for now
            flash('Quote created but PDF generation failed. You can retry from the quote page.', 'info')

        db.session.commit()

        current_app.logger.info('Quote generated: %s project=%d total=%.2f',
                                  quote_number, project_id, total)
        flash(f'Quote {quote_number} created.', 'success')
        return redirect(url_for('quote.view',
                                project_id=project_id, quote_id=quote.id))

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('generate quote error project=%d: %s', project_id, exc)
        flash('Failed to generate quote. Please try again.', 'error')
        return redirect(url_for('projects.detail', project_id=project_id))


# ------------------------------------------------------------------ #
#  GET /projects/<id>/quotes/<qid>
# ------------------------------------------------------------------ #
@quote_bp.route('/projects/<int:project_id>/quotes/<int:quote_id>')
@login_required
def view(project_id, quote_id):
    try:
        project = _own_project(project_id)
        quote   = _own_quote(quote_id, project_id)
        windows = project.windows.all()

        window_lines = []
        for w in windows:
            panes  = w.panes.all()
            price  = calculate_price(w, panes, current_user.tenant_id,
                                    design=(json.loads(w.design_json) if getattr(w, "design_json", None) else None))
            # get latest render/visualisation for this window
            from ..models import Visualisation
            vis = (Visualisation.query
                   .filter_by(window_id=w.id)
                   .order_by(Visualisation.created_at.desc())
                   .first())
            render_url = ('/uploads/' + vis.rendered_path) if (vis and vis.rendered_path) else None
            # parse design_json for hardware/extras display
            design = {}
            try:
                if getattr(w, 'design_json', None):
                    design = json.loads(w.design_json)
            except Exception:
                design = {}
            hw_list = []
            for cat, val in (design.get('hardware', {}) or {}).items():
                if cat.startswith('_'):
                    continue
                sel = val.get('sel') if isinstance(val, dict) else val
                if sel and sel != 'None':
                    qty = val.get('qty', '') if isinstance(val, dict) else ''
                    hw_list.append(f"{cat}: {sel}" + (f" ({qty})" if qty else ""))
            ex_list = []
            for key, item in (design.get('extras', {}) or {}).items():
                ex_list.append(item.get('name', key))
            for c in (design.get('customExtras', []) or []):
                if c.get('component'):
                    ex_list.append(c['component'])
            window_lines.append({
                'window':     w,
                'panes':      panes,
                'price':      price,
                'render_url': render_url,
                'hardware':   hw_list,
                'extras':     ex_list,
            })

        vat_amt = quote.vat_amount
        return render_template('quote.html',
                               project=project, quote=quote,
                               window_lines=window_lines, vat_amt=vat_amt)
    except Exception as exc:
        current_app.logger.exception('view quote error %d: %s', quote_id, exc)
        flash('Could not load quote.', 'error')
        return redirect(url_for('projects.detail', project_id=project_id))


# ------------------------------------------------------------------ #
#  GET /projects/<id>/quotes/<qid>/pdf
# ------------------------------------------------------------------ #
@quote_bp.route('/projects/<int:project_id>/quotes/<int:quote_id>/pdf')
@login_required
def download_pdf(project_id, quote_id):
    try:
        project = _own_project(project_id)
        quote   = _own_quote(quote_id, project_id)

        # if PDF exists on disk, serve it
        if quote.pdf_path:
            pdf_path = os.path.join(current_app.config['UPLOAD_FOLDER'], quote.pdf_path)
            if os.path.exists(pdf_path):
                return send_file(
                    pdf_path,
                    mimetype='application/pdf',
                    as_attachment=True,
                    download_name=f'{quote.quote_number}.pdf',
                )

        # regenerate on the fly
        windows      = project.windows.all()
        window_lines = []
        for w in windows:
            panes = w.panes.all()
            price = calculate_price(w, panes, current_user.tenant_id,
                                    design=(json.loads(w.design_json) if getattr(w, "design_json", None) else None))
            window_lines.append({'window': w, 'panes': panes, 'price': price})

        pdf_bytes = generate_quote_pdf(
            quote=quote, project=project, tenant=current_user.tenant,
            window_lines=window_lines, vat_amt=quote.vat_amount,
        )

        import io
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'{quote.quote_number}.pdf',
        )

    except Exception as exc:
        current_app.logger.exception('download_pdf error quote=%d: %s', quote_id, exc)
        flash('PDF download failed.', 'error')
        return redirect(url_for('quote.view', project_id=project_id, quote_id=quote_id))


# ------------------------------------------------------------------ #
#  POST /projects/<id>/quotes/<qid>/send  — mark as sent
# ------------------------------------------------------------------ #
@quote_bp.route('/projects/<int:project_id>/quotes/<int:quote_id>/send', methods=['POST'])
@login_required
def mark_sent(project_id, quote_id):
    try:
        from datetime import datetime
        project = _own_project(project_id)
        quote   = _own_quote(quote_id, project_id)
        quote.sent_at         = datetime.utcnow()
        project.status        = ProjectStatus.SENT
        db.session.commit()
        current_app.logger.info('Quote marked sent: %s', quote.quote_number)
        flash(f'Quote {quote.quote_number} marked as sent.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('mark_sent error quote=%d: %s', quote_id, exc)
        flash('Could not update quote status.', 'error')
    return redirect(url_for('quote.view', project_id=project_id, quote_id=quote_id))


# ------------------------------------------------------------------ #
#  POST /projects/<id>/quotes/<qid>/won  — mark project as won
# ------------------------------------------------------------------ #
@quote_bp.route('/projects/<int:project_id>/quotes/<int:quote_id>/won', methods=['POST'])
@login_required
def mark_won(project_id, quote_id):
    try:
        project = _own_project(project_id)
        project.status = ProjectStatus.WON
        db.session.commit()
        flash('Project marked as won. 🎉', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('mark_won error project=%d: %s', project_id, exc)
        flash('Could not update project status.', 'error')
    return redirect(url_for('quote.view', project_id=project_id, quote_id=quote_id))


# ------------------------------------------------------------------ #
#  POST /projects/<id>/quotes/<qid>/delete
# ------------------------------------------------------------------ #
@quote_bp.route('/projects/<int:project_id>/quotes/<int:quote_id>/delete', methods=['POST'])
@login_required
def delete(project_id, quote_id):
    try:
        _own_project(project_id)
        quote = _own_quote(quote_id, project_id)
        # remove PDF file if exists
        if quote.pdf_path:
            pdf_path = os.path.join(current_app.config['UPLOAD_FOLDER'], quote.pdf_path)
            try:
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)
            except Exception:
                pass
        db.session.delete(quote)
        db.session.commit()
        flash('Quote deleted.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('delete quote error %d: %s', quote_id, exc)
        flash('Could not delete quote.', 'error')
    return redirect(url_for('projects.detail', project_id=project_id))


# ------------------------------------------------------------------ #
#  Helpers
# ------------------------------------------------------------------ #
def _own_project(project_id):
    p = Project.query.filter_by(
        id=project_id, tenant_id=current_user.tenant_id
    ).first()
    if not p:
        abort(404)
    return p

def _own_quote(quote_id, project_id):
    q = Quote.query.filter_by(
        id=quote_id, project_id=project_id, tenant_id=current_user.tenant_id
    ).first()
    if not q:
        abort(404)
    return q


# ------------------------------------------------------------------ #
#  GET /projects/<id>/quotes/<qid>/print
#  Browser-native print-to-PDF — works on all platforms, no WeasyPrint needed.
# ------------------------------------------------------------------ #
@quote_bp.route('/projects/<int:project_id>/quotes/<int:quote_id>/print')
@login_required
def print_view(project_id, quote_id):
    try:
        project      = _own_project(project_id)
        quote        = _own_quote(quote_id, project_id)
        windows      = project.windows.all()
        window_lines = []
        for w in windows:
            panes = w.panes.all()
            price = calculate_price(w, panes, current_user.tenant_id,
                                    design=(json.loads(w.design_json) if getattr(w, "design_json", None) else None))
            window_lines.append({'window': w, 'panes': panes, 'price': price})
        vat_amt = quote.vat_amount
        return render_template('quote_print.html',
                               project=project, quote=quote,
                               tenant=current_user.tenant,
                               window_lines=window_lines, vat_amt=vat_amt)
    except Exception as exc:
        current_app.logger.exception('print_view error quote=%d: %s', quote_id, exc)
        flash('Could not load print view.', 'error')
        return redirect(url_for('quote.view', project_id=project_id, quote_id=quote_id))