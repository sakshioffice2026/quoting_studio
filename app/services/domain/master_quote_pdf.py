"""
Master Quotation PDF.

One PDF that carries everything the customer needs:
  - proposal narrative (executive summary, scope, commercial notes, next steps)
  - line items, charges and totals
  - payment stages (actual invoices once an order exists, planned schedule before)
  - manufacturing jobs (actual jobs once an order exists, planned process before)
  - terms

Rendered with WeasyPrint. Does not need LibreOffice or the DOCX template.
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP

from jinja2 import Environment

from ...models.manufacturing_job import ManufacturingJob, ProductionStage
from ...models.payment import Payment, PaymentStage, PaymentStatus
from .payment_service import DEFAULT_ADVANCE_PCT, stage_percentages
from .proposal_context_service import build_proposal_context
from .proposal_copy_service import generate_proposal_copy

logger = logging.getLogger(__name__)


def _resolve_visual_url(quotation):
    """Public customer link (visual preview + quotation); None if it cannot be created."""
    try:
        from flask import has_request_context, url_for
        if not has_request_context():
            return None
        from ...models.quotation import QuotationStatus
        from ...models.share_link import ShareLinkType
        from .share_link_service import get_or_create_link, create_visualiser_link
        if quotation.status in (QuotationStatus.DRAFT, QuotationStatus.PENDING_DISCOUNT_APPROVAL):
            link = create_visualiser_link(quotation.tenant_id, quotation.id)
        else:
            link = get_or_create_link(quotation.tenant_id, ShareLinkType.MASTER_QUOTE, quotation.id)
        return url_for('public_share.view', token=link.token, _external=True)
    except Exception as exc:
        logger.warning('Visual link not added to master quote PDF: %s', exc)
        return None


def _qr_data_uri(url):
    """Optional QR code (needs the 'segno' package); silently skipped when absent."""
    try:
        import base64, io, segno
        buf = io.BytesIO()
        segno.make(url, error='m').save(buf, kind='svg', scale=3, border=1)
        return 'data:image/svg+xml;base64,' + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None

logger = logging.getLogger(__name__)

_DATE_FMT = "%d %b %Y"

_PLANNED_DUE = {
    PaymentStage.ADVANCE:         "On acceptance",
    PaymentStage.PRE_DISPATCH:    "Before dispatch",
    PaymentStage.ON_INSTALLATION: "On installation",
    PaymentStage.RETENTION:       "After handover",
}


# ------------------------------------------------------------------ #
#  Small helpers
# ------------------------------------------------------------------ #

def _money(value, symbol: str) -> str:
    try:
        return f"{symbol}{Decimal(str(value or 0)):,.2f}"
    except Exception:
        return f"{symbol}0.00"


def _date(value) -> str:
    if not value:
        return ""
    try:
        return value.strftime(_DATE_FMT)
    except Exception:
        return str(value)


def _percent(part: Decimal, total: Decimal) -> str:
    if not total:
        return "-"
    pct = (part / total * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{pct:f}".rstrip("0").rstrip(".") + "%"


def _size(width, height) -> str:
    if width and height:
        try:
            return f"{int(width)} x {int(height)} mm"
        except (TypeError, ValueError):
            return f"{width} x {height} mm"
    return "-"


# ------------------------------------------------------------------ #
#  Payment stages
# ------------------------------------------------------------------ #

def _payment_section(quotation, symbol: str) -> dict:
    total = Decimal(str(quotation.grand_total or 0))
    order = quotation.active_order

    if order:
        total = Decimal(str(order.total_amount or total))
        payments = (Payment.query
                    .filter_by(order_id=order.id)
                    .order_by(Payment.id)
                    .all())
        if payments:
            rows = []
            for p in payments:
                invoice = Decimal(str(p.invoice_amount or 0))
                received = Decimal(str(p.amount_received or 0))
                rows.append({
                    "stage":    PaymentStage.LABELS.get(p.payment_stage, p.payment_stage),
                    "percent":  _percent(invoice, total),
                    "amount":   _money(invoice, symbol),
                    "received": _money(received, symbol),
                    "status":   PaymentStatus.LABELS.get(p.status, p.status),
                    "due":      _date(p.due_date) or "-",
                })
            return {"planned": False, "rows": rows}

    percentages = stage_percentages(DEFAULT_ADVANCE_PCT)
    rows = []
    running = Decimal("0.00")
    stages = list(PaymentStage.ALL)
    for index, stage in enumerate(stages):
        pct = percentages[stage]
        if index == len(stages) - 1:
            amount = total - running
        else:
            amount = (total * pct / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
        running += amount
        rows.append({
            "stage":    PaymentStage.LABELS.get(stage, stage),
            "percent":  f"{pct:f}".rstrip("0").rstrip(".") + "%",
            "amount":   _money(amount, symbol),
            "received": "-",
            "status":   "Planned",
            "due":      _PLANNED_DUE.get(stage, "-"),
        })
    return {"planned": True, "rows": rows}


# ------------------------------------------------------------------ #
#  Manufacturing jobs
# ------------------------------------------------------------------ #

def _manufacturing_section(quotation) -> dict:
    stage_names = [ProductionStage.LABELS[s] for s in ProductionStage.ALL]
    order = quotation.active_order

    if order:
        jobs = (ManufacturingJob.query
                .filter_by(order_id=order.id)
                .order_by(ManufacturingJob.id)
                .all())
        if jobs:
            rows = []
            for job in jobs:
                opening = job.opening
                rows.append({
                    "job":     job.job_number,
                    "item":    opening.label if opening else "-",
                    "size":    _size(opening.width_mm, opening.height_mm) if opening else "-",
                    "stage":   job.stage_label,
                    "status":  job.status_label,
                    "planned": _date(job.planned_completion_date) or "-",
                    "done":    _date(job.actual_completion_date) or "-",
                })
            return {"planned": False, "rows": rows, "stages": stage_names}

    rows = []
    for index, item in enumerate(quotation.line_items, start=1):
        rows.append({
            "job":     f"Job {index}",
            "item":    str(item.get("label") or f"Item {index}"),
            "size":    _size(item.get("width_mm"), item.get("height_mm")),
            "stage":   "Not started",
            "status":  "Planned",
            "planned": "-",
            "done":    "-",
        })
    return {"planned": True, "rows": rows, "stages": stage_names}


# ------------------------------------------------------------------ #
#  HTML template
# ------------------------------------------------------------------ #

_TEMPLATE_SRC = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  @page {
    size: A4;
    margin: 18mm 16mm 20mm 16mm;
    @bottom-center {
      content: "{{ s.quotation_number }} · Master Quotation · Page " counter(page) " of " counter(pages);
      font-family: "DejaVu Sans", Arial, sans-serif;
      font-size: 8pt;
      color: #8A93A6;
    }
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: "DejaVu Sans", Arial, Helvetica, sans-serif; font-size: 9.5pt; color: #1B2430; line-height: 1.45; }

  .letterhead { display: flex; justify-content: space-between; align-items: flex-start;
                border-bottom: 2.5pt solid #C97B3D; padding-bottom: 10pt; margin-bottom: 14pt; }
  .company { font-size: 19pt; font-weight: 700; }
  .company-meta { font-size: 8.5pt; color: #8A93A6; margin-top: 3pt; }
  .meta { text-align: right; font-size: 8.5pt; color: #556; line-height: 1.7; }
  .qno { font-size: 13pt; font-weight: 700; color: #C97B3D; }

  .customer { background: #F6F3EC; border-left: 3pt solid #C97B3D; padding: 8pt 12pt; margin-bottom: 14pt; }
  .label { font-size: 7.5pt; text-transform: uppercase; letter-spacing: .06em; color: #8A93A6; }
  .cname { font-size: 12pt; font-weight: 700; }
  .visual-cta { display: flex; justify-content: space-between; align-items: center; gap: 12pt; background: #FDF6EE; border: 1pt solid #C97B3D; padding: 8pt 12pt; margin-bottom: 14pt; }

  h2 { font-size: 11pt; color: #1B2430; margin: 16pt 0 6pt; padding-bottom: 3pt; border-bottom: 1pt solid #E5E7EB; }
  p.para { margin-bottom: 6pt; white-space: pre-line; }
  ol.steps { margin: 4pt 0 0 16pt; }
  ol.steps li { margin-bottom: 3pt; }

  table { width: 100%; border-collapse: collapse; margin-top: 4pt; }
  th { text-align: left; font-size: 7.5pt; text-transform: uppercase; letter-spacing: .05em;
       color: #6B7280; padding: 5pt 6pt; border-bottom: 1.2pt solid #D1D5DB; background: #FAFAF8; }
  td { padding: 5pt 6pt; border-bottom: .6pt solid #EEF0F3; vertical-align: top; }
  .num { text-align: right; white-space: nowrap; }
  tr { page-break-inside: avoid; }

  .totals { width: 55%; margin: 8pt 0 0 auto; }
  .totals div { display: flex; justify-content: space-between; padding: 3pt 0; }
  .totals .grand { border-top: 1.5pt solid #1B2430; margin-top: 4pt; padding-top: 6pt;
                   font-size: 12pt; font-weight: 700; color: #C97B3D; }

  .note { font-size: 8pt; color: #8A93A6; margin-top: 4pt; }
  .pipeline { margin-top: 6pt; font-size: 8pt; color: #556; }
  .pipeline span { display: inline-block; background: #F1F3F6; border-radius: 8pt; padding: 2pt 7pt; margin: 0 2pt 3pt 0; }
  .terms p { margin-bottom: 4pt; }
  .section { page-break-inside: avoid; }
</style>
</head>
<body>

<div class="letterhead">
  <div>
    <div class="company">{{ s.company_name or 'Quotation' }}</div>
    {% if s.company_email %}<div class="company-meta">{{ s.company_email }}</div>{% endif %}
  </div>
  <div class="meta">
    <div class="qno">{{ s.quotation_number }}</div>
    <div>Master Quotation · Version {{ s.quotation_version }}</div>
    {% if s.quotation_date %}<div>Date: {{ s.quotation_date }}</div>{% endif %}
    {% if s.validity_date %}<div>Valid until: {{ s.validity_date }}</div>{% endif %}
  </div>
</div>

<div class="customer">
  <div class="label">Prepared for</div>
  <div class="cname">{{ s.customer_name or 'Customer' }}</div>
  {% if s.project_address %}<div>{{ s.project_address }}</div>{% endif %}
</div>

{% if visual_url %}
<div class="visual-cta">
  <div>
    <div class="label">View your design</div>
    <div style="font-size:10pt;font-weight:700;">See your windows and doors on your home, approve or request changes online</div>
    <a href="{{ visual_url }}" style="color:#C97B3D;font-size:8.5pt;word-break:break-all;">{{ visual_url }}</a>
  </div>
  {% if qr %}<img src="{{ qr }}" style="width:72pt;height:72pt;">{% endif %}
</div>
{% endif %}

{# ---------- Proposal ---------- #}
{% if copy.executive_summary %}
<h2>Overview</h2>
<p class="para">{{ copy.executive_summary }}</p>
{% endif %}

{% if copy.scope_of_work %}
<h2>Scope of work</h2>
<p class="para">{{ copy.scope_of_work }}</p>
{% endif %}

{# ---------- Items ---------- #}
<h2>Items</h2>
<table>
  <thead>
    <tr><th>#</th><th>Item</th><th>Material</th><th>Size</th><th class="num">Qty</th><th class="num">Amount</th></tr>
  </thead>
  <tbody>
    {% for r in item_rows %}
    <tr>
      <td>{{ r.item_no }}</td>
      <td><strong>{{ r.item_label }}</strong></td>
      <td>{{ r.item_material }}</td>
      <td>{{ r.item_size }}</td>
      <td class="num">{{ r.item_qty }}</td>
      <td class="num">{{ r.item_amount }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

{% if charge_rows %}
<table>
  <thead><tr><th>Additional charges</th><th>Details</th><th class="num">Amount</th></tr></thead>
  <tbody>
    {% for c in charge_rows %}
    <tr><td>{{ c.charge_label }}</td><td>{{ c.charge_details }}</td><td class="num">{{ c.charge_amount }}</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endif %}

<div class="totals">
  <div><span>Subtotal</span><span>{{ s.subtotal }}</span></div>
  {% if s.discount_pct not in ('0', '', '0.0') %}
  <div><span>Discount ({{ s.discount_pct }}%)</span><span>-{{ s.discount_amount }}</span></div>
  {% endif %}
  <div><span>Tax ({{ s.tax_rate }})</span><span>{{ s.tax_amount }}</span></div>
  <div class="grand"><span>Total</span><span>{{ s.grand_total }}</span></div>
</div>

{# ---------- Payment stages ---------- #}
<div class="section">
  <h2>Payment stages</h2>
  <table>
    <thead>
      <tr><th>Stage</th><th class="num">Share</th><th class="num">Amount</th><th class="num">Received</th><th>Due</th><th>Status</th></tr>
    </thead>
    <tbody>
      {% for p in payment.rows %}
      <tr>
        <td><strong>{{ p.stage }}</strong></td>
        <td class="num">{{ p.percent }}</td>
        <td class="num">{{ p.amount }}</td>
        <td class="num">{{ p.received }}</td>
        <td>{{ p.due }}</td>
        <td>{{ p.status }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% if payment.planned %}
  <div class="note">Planned schedule. Final invoices are raised after the order is confirmed.</div>
  {% endif %}
</div>

{# ---------- Manufacturing jobs ---------- #}
<div class="section">
  <h2>Manufacturing jobs</h2>
  <table>
    <thead>
      <tr><th>Job</th><th>Item</th><th>Size</th><th>Stage</th><th>Status</th><th>Planned</th><th>Completed</th></tr>
    </thead>
    <tbody>
      {% for j in manufacturing.rows %}
      <tr>
        <td><strong>{{ j.job }}</strong></td>
        <td>{{ j.item }}</td>
        <td>{{ j.size }}</td>
        <td>{{ j.stage }}</td>
        <td>{{ j.status }}</td>
        <td>{{ j.planned }}</td>
        <td>{{ j.done }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <div class="pipeline">
    Process:
    {% for st in manufacturing.stages %}<span>{{ st }}</span>{% endfor %}
  </div>
  {% if manufacturing.planned %}
  <div class="note">Jobs are created once the order is confirmed and the advance is received.</div>
  {% endif %}
</div>

{# ---------- Commercial notes / next steps ---------- #}
{% if copy.commercial_notes %}
<h2>Commercial notes</h2>
<p class="para">{{ copy.commercial_notes }}</p>
{% endif %}

{% if copy.next_steps %}
<h2>Next steps</h2>
<ol class="steps">
  {% for step in copy.next_steps %}<li>{{ step }}</li>{% endfor %}
</ol>
{% endif %}

{# ---------- Terms ---------- #}
<div class="section terms">
  <h2>Terms</h2>
  {% if s.payment_terms and s.payment_terms != '-' %}<p><strong>Payment terms:</strong> {{ s.payment_terms }}</p>{% endif %}
  {% if s.validity_date %}<p><strong>Validity:</strong> until {{ s.validity_date }}</p>{% endif %}
  {% if s.warranty_months %}<p><strong>Warranty:</strong> {{ s.warranty_months }} months{% if s.warranty_terms %} — {{ s.warranty_terms }}{% endif %}</p>{% endif %}
  {% if s.amc_tier and s.amc_tier != 'Not offered' %}<p><strong>AMC:</strong> {{ s.amc_tier }}{% if s.amc_price %} ({{ s.amc_price }}){% endif %}</p>{% endif %}
</div>

</body>
</html>
"""

_ENV = Environment(autoescape=True)
_TEMPLATE = _ENV.from_string(_TEMPLATE_SRC)


# ------------------------------------------------------------------ #
#  Public API
# ------------------------------------------------------------------ #

def generate_master_quote_pdf(
    quotation,
    project,
    tenant,
    use_llm: bool = False,
    currency_symbol: str | None = None,
    visual_url: str | None = None,
) -> bytes:
    """Return the Master Quotation as PDF bytes.

    use_llm defaults to False so the customer download is fast and
    deterministic; the built-in fallback copy is used for the narrative.
    """
    if not currency_symbol:
        currency_symbol = tenant.currency_symbol if tenant is not None else "\u20b9"
    visual_url = visual_url or _resolve_visual_url(quotation)
    context = build_proposal_context(quotation, project, tenant, currency_symbol)
    copy_data = generate_proposal_copy(context["llm_input"], use_llm=use_llm)

    html = _TEMPLATE.render(
        s=context["scalars"],
        item_rows=context["item_rows"],
        charge_rows=context["charge_rows"],
        copy=copy_data,
        payment=_payment_section(quotation, currency_symbol),
        manufacturing=_manufacturing_section(quotation),
        visual_url=visual_url,
        qr=_qr_data_uri(visual_url) if visual_url else None,
    )

    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        logger.warning("WeasyPrint unavailable (%s); using reportlab for master quote %s",
                       exc, quotation.quotation_number)
        return _generate_with_reportlab(quotation, project, tenant, use_llm, currency_symbol, visual_url)

    pdf_bytes = HTML(string=html).write_pdf()
    logger.info("Master quote PDF rendered: %s size=%d bytes",
                quotation.quotation_number, len(pdf_bytes))
    return pdf_bytes


# ------------------------------------------------------------------ #
#  reportlab fallback (pure Python, no GTK/Pango needed — works on Windows)
# ------------------------------------------------------------------ #

def _generate_with_reportlab(quotation, project, tenant, use_llm: bool, currency_symbol: str, visual_url: str | None = None) -> bytes:
    import io
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    # Built-in PDF fonts have no rupee glyph.
    code = (tenant.currency_code if tenant is not None and getattr(tenant, "currency_code", None) else "INR")
    try:
        currency_symbol.encode("cp1252")
        symbol = currency_symbol
    except UnicodeEncodeError:
        symbol = "Rs. " if code == "INR" else f"{code} "

    context = build_proposal_context(quotation, project, tenant, symbol)
    copy_data = generate_proposal_copy(context["llm_input"], use_llm=use_llm)
    s = context["scalars"]
    payment = _payment_section(quotation, symbol)
    manufacturing = _manufacturing_section(quotation)

    navy = colors.HexColor("#1B2430")
    copper = colors.HexColor("#C97B3D")
    grey = colors.HexColor("#8A93A6")
    line = colors.HexColor("#E2DDD0")

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("mq_h1", parent=styles["Heading1"], fontSize=18, spaceAfter=2, textColor=navy)
    h2 = ParagraphStyle("mq_h2", parent=styles["Heading2"], fontSize=11, spaceBefore=14,
                        spaceAfter=6, textColor=navy)
    meta = ParagraphStyle("mq_meta", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#556"))
    body = ParagraphStyle("mq_body", parent=styles["Normal"], fontSize=9.5, leading=13, spaceAfter=5)
    cell = ParagraphStyle("mq_cell", parent=styles["Normal"], fontSize=8, leading=10)
    cell_r = ParagraphStyle("mq_cell_r", parent=cell, alignment=TA_RIGHT)
    head = ParagraphStyle("mq_head", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    head_r = ParagraphStyle("mq_head_r", parent=head, alignment=TA_RIGHT)
    note = ParagraphStyle("mq_note", parent=styles["Normal"], fontSize=8, textColor=grey, spaceBefore=3)

    def text(value) -> str:
        return escape(str(value if value is not None else ""))

    def para(value, style=body):
        return Paragraph(text(value).replace("\n", "<br/>"), style)

    def build_table(rows, widths, right_cols=()):
        data = []
        for r_index, row in enumerate(rows):
            out = []
            for c_index, value in enumerate(row):
                right = c_index in right_cols
                if r_index == 0:
                    out.append(Paragraph(text(value), head_r if right else head))
                else:
                    out.append(Paragraph(text(value), cell_r if right else cell))
            data.append(out)
        table = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, line),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAF8")]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return table

    story = []

    # ---- Header ----
    story.append(Paragraph(text(s.get("company_name") or "Quotation"), h1))
    if s.get("company_email"):
        story.append(Paragraph(text(s["company_email"]), meta))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"<b>{text(s['quotation_number'])}</b> &middot; Master Quotation &middot; "
        f"Version {text(s['quotation_version'])}", meta))
    if s.get("quotation_date"):
        story.append(Paragraph(f"Date: {text(s['quotation_date'])}", meta))
    if s.get("validity_date"):
        story.append(Paragraph(f"Valid until: {text(s['validity_date'])}", meta))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>{text(s.get('customer_name') or 'Customer')}</b>", styles["Heading2"]))
    if s.get("project_address"):
        story.append(Paragraph(text(s["project_address"]), meta))
    if visual_url:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            '<b>View your design online:</b> <link href="' + text(visual_url) + '" color="#C97B3D">'
            + text(visual_url) + '</link>', body))

    # ---- Proposal narrative ----
    if copy_data.get("executive_summary"):
        story.append(Paragraph("Overview", h2))
        story.append(para(copy_data["executive_summary"]))
    if copy_data.get("scope_of_work"):
        story.append(Paragraph("Scope of work", h2))
        story.append(para(copy_data["scope_of_work"]))

    # ---- Items ----
    story.append(Paragraph("Items", h2))
    item_rows = [["#", "Item", "Material", "Size", "Qty", "Amount"]]
    for r in context["item_rows"]:
        item_rows.append([r["item_no"], r["item_label"], r["item_material"],
                          r["item_size"], r["item_qty"], r["item_amount"]])
    story.append(build_table(item_rows, [8, 52, 30, 32, 12, 44], right_cols=(4, 5)))

    if context["charge_rows"]:
        story.append(Spacer(1, 6))
        charge_rows = [["Additional charges", "Details", "Amount"]]
        for c in context["charge_rows"]:
            charge_rows.append([c["charge_label"], c["charge_details"], c["charge_amount"]])
        story.append(build_table(charge_rows, [60, 74, 44], right_cols=(2,)))

    # ---- Totals ----
    story.append(Spacer(1, 8))
    totals = [["Subtotal", s["subtotal"]]]
    if s.get("discount_pct") not in ("0", "", "0.0", None):
        totals.append([f"Discount ({s['discount_pct']}%)", f"-{s['discount_amount']}"])
    totals.append([f"Tax ({s['tax_rate']})", s["tax_amount"]])
    totals.append(["Total", s["grand_total"]])
    totals_table = Table(
        [[Paragraph(text(a), cell), Paragraph(text(b), cell_r)] for a, b in totals],
        colWidths=[50 * mm, 40 * mm], hAlign="RIGHT",
    )
    totals_table.setStyle(TableStyle([
        ("LINEABOVE", (0, -1), (-1, -1), 1, navy),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(totals_table)

    # ---- Payment stages ----
    story.append(Paragraph("Payment stages", h2))
    pay_rows = [["Stage", "Share", "Amount", "Received", "Due", "Status"]]
    for p in payment["rows"]:
        pay_rows.append([p["stage"], p["percent"], p["amount"], p["received"], p["due"], p["status"]])
    story.append(build_table(pay_rows, [34, 18, 36, 36, 28, 26], right_cols=(1, 2, 3)))
    if payment["planned"]:
        story.append(Paragraph(
            "Planned schedule. Final invoices are raised after the order is confirmed.", note))

    # ---- Manufacturing jobs ----
    story.append(Paragraph("Manufacturing jobs", h2))
    job_rows = [["Job", "Item", "Size", "Stage", "Status", "Planned", "Completed"]]
    for j in manufacturing["rows"]:
        job_rows.append([j["job"], j["item"], j["size"], j["stage"],
                         j["status"], j["planned"], j["done"]])
    story.append(build_table(job_rows, [28, 36, 28, 22, 22, 21, 21]))
    story.append(Paragraph("Process: " + " > ".join(manufacturing["stages"]), note))
    if manufacturing["planned"]:
        story.append(Paragraph(
            "Jobs are created once the order is confirmed and the advance is received.", note))

    # ---- Commercial notes / next steps ----
    if copy_data.get("commercial_notes"):
        story.append(Paragraph("Commercial notes", h2))
        story.append(para(copy_data["commercial_notes"]))
    if copy_data.get("next_steps"):
        story.append(Paragraph("Next steps", h2))
        for index, step in enumerate(copy_data["next_steps"], start=1):
            story.append(para(f"{index}. {step}"))

    # ---- Terms ----
    story.append(Paragraph("Terms", h2))
    if s.get("payment_terms") and s["payment_terms"] != "-":
        story.append(Paragraph(f"<b>Payment terms:</b> {text(s['payment_terms'])}", body))
    if s.get("validity_date"):
        story.append(Paragraph(f"<b>Validity:</b> until {text(s['validity_date'])}", body))
    if s.get("warranty_months"):
        warranty = f"{text(s['warranty_months'])} months"
        if s.get("warranty_terms"):
            warranty += f" - {text(s['warranty_terms'])}"
        story.append(Paragraph(f"<b>Warranty:</b> {warranty}", body))
    if s.get("amc_tier") and s["amc_tier"] != "Not offered":
        amc = text(s["amc_tier"]) + (f" ({text(s['amc_price'])})" if s.get("amc_price") else "")
        story.append(Paragraph(f"<b>AMC:</b> {amc}", body))

    number = s.get("quotation_number", "")

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(grey)
        canvas.drawCentredString(
            A4[0] / 2, 10 * mm, f"{number} \u00b7 Master Quotation \u00b7 Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=18 * mm, bottomMargin=20 * mm,
        leftMargin=16 * mm, rightMargin=16 * mm,
        title=f"Master Quotation {number}",
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)

    pdf_bytes = buf.getvalue()
    logger.info("Master quote PDF rendered (reportlab): %s size=%d bytes", number, len(pdf_bytes))
    return pdf_bytes
