from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user

from ..extensions import db
from ..models import User, Tenant, UserRole, PricingRule, OpenerPricingRule, GlazingPricingRule

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')
log = lambda: current_app.logger


# ------------------------------------------------------------------ #
#  Login
# ------------------------------------------------------------------ #
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'

        try:
            user = User.query.filter_by(email=email, is_active=True).first()

            if user and user.check_password(password):
                user.last_login = datetime.utcnow()
                db.session.commit()
                login_user(user, remember=remember)
                current_app.logger.info('Login success: %s (tenant=%s)', email, user.tenant_id)
                nxt = request.args.get('next')
                return redirect(nxt or url_for('dashboard.index'))

            current_app.logger.warning('Login failed for email: %s', email)
            flash('Invalid email or password.', 'error')

        except Exception as exc:
            current_app.logger.exception('Unexpected error during login for %s: %s', email, exc)
            flash('An unexpected error occurred. Please try again.', 'error')

    return render_template('auth/login.html')


# ------------------------------------------------------------------ #
#  Register
# ------------------------------------------------------------------ #
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form_data = {}

    if request.method == 'POST':
        company_name = request.form.get('company_name', '').strip()
        full_name    = request.form.get('full_name', '').strip()
        email        = request.form.get('email', '').strip().lower()
        password     = request.form.get('password', '')
        confirm      = request.form.get('confirm_password', '')

        form_data = dict(company_name=company_name, full_name=full_name, email=email)

        errors = []
        if not company_name:
            errors.append('Company name is required.')
        if not full_name:
            errors.append('Your name is required.')
        if not email or '@' not in email:
            errors.append('A valid email address is required.')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        if password != confirm:
            errors.append('Passwords do not match.')

        try:
            if not errors and User.query.filter_by(email=email).first():
                errors.append('An account with this email already exists.')
        except Exception as exc:
            current_app.logger.exception('DB error checking duplicate email: %s', exc)
            flash('A database error occurred. Please try again.', 'error')
            return render_template('auth/register.html', **form_data)

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('auth/register.html', **form_data)

        try:
            base_slug = Tenant.generate_slug(company_name)
            slug, n = base_slug, 1
            while Tenant.query.filter_by(slug=slug).first():
                slug = f"{base_slug}-{n}"
                n += 1

            tenant = Tenant(name=company_name, slug=slug, contact_email=email)
            db.session.add(tenant)
            db.session.flush()

            user = User(tenant_id=tenant.id, email=email,
                        full_name=full_name, role=UserRole.ADMIN)
            user.set_password(password)
            db.session.add(user)

            _seed_pricing_rules(tenant.id)
            db.session.commit()

            current_app.logger.info('New tenant registered: %s (slug=%s, user=%s)',
                                    company_name, slug, email)
            login_user(user)
            flash(f'Welcome to Quoting Studio, {full_name}!', 'success')
            return redirect(url_for('dashboard.index'))

        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception('Registration failed for %s: %s', email, exc)
            flash('Registration failed due to a server error. Please try again.', 'error')
            return render_template('auth/register.html', **form_data)

    return render_template('auth/register.html', **form_data)


# ------------------------------------------------------------------ #
#  Logout
# ------------------------------------------------------------------ #
@auth_bp.route('/logout')
@login_required
def logout():
    current_app.logger.info('Logout: %s', current_user.email)
    logout_user()
    return redirect(url_for('auth.login'))


# ------------------------------------------------------------------ #
#  Seed default pricing rules for a new tenant
# ------------------------------------------------------------------ #
def _seed_pricing_rules(tenant_id: int) -> None:
    materials = [
        ('Aluminium', 3.20,  95.00, 140.00),
        ('PVCu',      1.80,  85.00, 120.00),
        ('Timber',    2.40,  90.00, 160.00),
        ('Steel',     4.50,  95.00, 180.00),
    ]
    for mat, frame, glass, fitting in materials:
        db.session.add(PricingRule(
            tenant_id=tenant_id, material=mat,
            frame_cost_per_metre=frame,
            glass_cost_per_m2=glass,
            fitting_fixed=fitting,
        ))

    openers = [
        ('Fixed light',         0),
        ('Top hung casement',  48),
        ('Side hung casement', 52),
        ('Tilt & turn',        85),
        ('Sliding sash',      110),
    ]
    for opener, cost in openers:
        db.session.add(OpenerPricingRule(
            tenant_id=tenant_id, opener_type=opener, hardware_cost=cost,
        ))

    glazings = [
        ('Double, Low-E', 0.00),
        ('Triple glazed', 1.35),
        ('Obscure',       0.15),
        ('Acoustic',      1.60),
    ]
    for glazing, mult in glazings:
        db.session.add(GlazingPricingRule(
            tenant_id=tenant_id, glazing_type=glazing, cost_multiplier=mult,
        ))
