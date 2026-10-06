import os, uuid
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, current_app)
from flask_login import login_required, current_user
from functools import wraps

from ..extensions import db
from ..models import (User, UserRole, PricingRule,
                       OpenerPricingRule, GlazingPricingRule)

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')


# ---- admin-only decorator ----------------------------------------
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash('Admin access required.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


# ================================================================
#  COMPANY
# ================================================================
@settings_bp.route('/', methods=['GET', 'POST'])
@settings_bp.route('/company', methods=['GET', 'POST'])
@login_required
@admin_required
def company():
    tenant = current_user.tenant
    if request.method == 'POST':
        try:
            name         = request.form.get('name', '').strip()
            email        = request.form.get('contact_email', '').strip()
            colour       = request.form.get('brand_colour', '#C97B3D').strip()
            currency_code = request.form.get(
                'currency_code', tenant.currency_code or 'INR'
            ).strip().upper()

            if not name:
                flash('Company name is required.', 'error')
                return render_template('settings/company.html', tenant=tenant)

            if currency_code not in tenant.CURRENCIES:
                flash('Invalid currency selected.', 'error')
                return render_template('settings/company.html', tenant=tenant)

            tenant.name          = name
            tenant.contact_email = email or tenant.contact_email
            tenant.brand_colour  = colour if colour.startswith('#') else tenant.brand_colour
            tenant.currency_code = currency_code
            db.session.commit()
            current_app.logger.info('Tenant settings updated: id=%d', tenant.id)
            flash('Company settings saved.', 'success')
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception('Company settings save error: %s', exc)
            flash('Failed to save settings.', 'error')

    return render_template('settings/company.html', tenant=tenant)
