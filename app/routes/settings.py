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
            name   = request.form.get('name', '').strip()
            email  = request.form.get('contact_email', '').strip()
            colour = request.form.get('brand_colour', '#C97B3D').strip()

            if not name:
                flash('Company name is required.', 'error')
                return render_template('settings/company.html', tenant=tenant)

            tenant.name         = name
            tenant.contact_email= email or tenant.contact_email
            tenant.brand_colour = colour if colour.startswith('#') else tenant.brand_colour
            db.session.commit()
            current_app.logger.info('Tenant settings updated: id=%d', tenant.id)
            flash('Company settings saved.', 'success')
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception('Company settings save error: %s', exc)
            flash('Failed to save settings.', 'error')

    return render_template('settings/company.html', tenant=tenant)


# ------------------------------------------------------------------ #
#  Logo upload
# ------------------------------------------------------------------ #
@settings_bp.route('/logo', methods=['POST'])
@login_required
@admin_required
def upload_logo():
    tenant = current_user.tenant
    try:
        if 'logo' not in request.files or request.files['logo'].filename == '':
            flash('No file selected.', 'error')
            return redirect(url_for('settings.company'))

        file = request.files['logo']
        ext  = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in {'png', 'jpg', 'jpeg', 'svg', 'webp'}:
            flash('Only PNG, JPG, SVG or WEBP allowed.', 'error')
            return redirect(url_for('settings.company'))

        logo_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'logos')
        os.makedirs(logo_dir, exist_ok=True)
        filename = f'tenant-{tenant.id}-{uuid.uuid4().hex[:8]}.{ext}'
        file.save(os.path.join(logo_dir, filename))

        # remove old logo file
        if tenant.logo_path:
            old = os.path.join(current_app.config['UPLOAD_FOLDER'], tenant.logo_path)
            try:
                if os.path.exists(old): os.remove(old)
            except Exception: pass

        tenant.logo_path = f'logos/{filename}'
        db.session.commit()
        flash('Logo updated.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Logo upload error: %s', exc)
        flash('Logo upload failed.', 'error')
    return redirect(url_for('settings.company'))


# ================================================================
#  PRICING
# ================================================================
@settings_bp.route('/pricing', methods=['GET', 'POST'])
@login_required
@admin_required
def pricing():
    tid = current_user.tenant_id
    if request.method == 'POST':
        try:
            # material rules
            for mat in ['Aluminium', 'PVCu', 'Timber', 'Steel']:
                rule = PricingRule.query.filter_by(tenant_id=tid, material=mat).first()
                if not rule:
                    rule = PricingRule(tenant_id=tid, material=mat)
                    db.session.add(rule)
                key = mat.lower().replace(' ', '_').replace('&', '')
                rule.frame_cost_per_metre = float(request.form.get(f'frame_{key}', rule.frame_cost_per_metre))
                rule.glass_cost_per_m2    = float(request.form.get(f'glass_{key}', rule.glass_cost_per_m2))
                rule.fitting_fixed        = float(request.form.get(f'fitting_{key}', rule.fitting_fixed))

            # opener hardware
            for opener in ['Fixed light','Top hung casement','Side hung casement','Tilt & turn','Sliding sash']:
                rule = OpenerPricingRule.query.filter_by(tenant_id=tid, opener_type=opener).first()
                if not rule:
                    rule = OpenerPricingRule(tenant_id=tid, opener_type=opener)
                    db.session.add(rule)
                fkey = 'hw_' + opener.lower().replace(' ', '_').replace('&', 'and')
                rule.hardware_cost = float(request.form.get(fkey, rule.hardware_cost))

            # glazing multipliers
            for glazing in ['Double, Low-E','Triple glazed','Obscure','Acoustic']:
                rule = GlazingPricingRule.query.filter_by(tenant_id=tid, glazing_type=glazing).first()
                if not rule:
                    rule = GlazingPricingRule(tenant_id=tid, glazing_type=glazing)
                    db.session.add(rule)
                fkey = 'gl_' + glazing.lower().replace(', ', '_').replace(' ', '_')
                rule.cost_multiplier = float(request.form.get(fkey, rule.cost_multiplier))

            db.session.commit()
            flash('Pricing rules saved.', 'success')
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(f'Invalid value — {exc}', 'error')
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception('Pricing save error: %s', exc)
            flash('Failed to save pricing.', 'error')
        return redirect(url_for('settings.pricing'))

    mat_rules    = {r.material: r for r in PricingRule.query.filter_by(tenant_id=tid).all()}
    opener_rules = {r.opener_type: r for r in OpenerPricingRule.query.filter_by(tenant_id=tid).all()}
    glazing_rules= {r.glazing_type: r for r in GlazingPricingRule.query.filter_by(tenant_id=tid).all()}
    return render_template('settings/pricing.html',
                           mat_rules=mat_rules,
                           opener_rules=opener_rules,
                           glazing_rules=glazing_rules)


# ================================================================
#  TEAM
# ================================================================
@settings_bp.route('/team')
@login_required
@admin_required
def team():
    members = (User.query
               .filter_by(tenant_id=current_user.tenant_id)
               .order_by(User.created_at)
               .all())
    return render_template('settings/team.html', members=members)


@settings_bp.route('/team/invite', methods=['POST'])
@login_required
@admin_required
def invite():
    try:
        full_name = request.form.get('full_name', '').strip()
        email     = request.form.get('email', '').strip().lower()
        role      = request.form.get('role', UserRole.MEMBER)
        password  = request.form.get('password', '').strip()

        errors = []
        if not full_name: errors.append('Name is required.')
        if not email or '@' not in email: errors.append('Valid email required.')
        if len(password) < 8: errors.append('Password must be at least 8 characters.')
        if role not in [UserRole.ADMIN, UserRole.MEMBER]: role = UserRole.MEMBER
        if User.query.filter_by(email=email).first(): errors.append('Email already in use.')

        if errors:
            for e in errors: flash(e, 'error')
            return redirect(url_for('settings.team'))

        user = User(tenant_id=current_user.tenant_id,
                    email=email, full_name=full_name, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        current_app.logger.info('Team member invited: %s by %s', email, current_user.email)
        flash(f'{full_name} added to the team.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Invite error: %s', exc)
        flash('Failed to add team member.', 'error')
    return redirect(url_for('settings.team'))


@settings_bp.route('/team/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_member(user_id):
    try:
        if user_id == current_user.id:
            flash("You can't deactivate yourself.", 'error')
            return redirect(url_for('settings.team'))
        user = User.query.filter_by(
            id=user_id, tenant_id=current_user.tenant_id
        ).first_or_404()
        user.is_active = not user.is_active
        db.session.commit()
        state = 'activated' if user.is_active else 'deactivated'
        flash(f'{user.full_name} {state}.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('toggle_member error uid=%d: %s', user_id, exc)
        flash('Could not update member.', 'error')
    return redirect(url_for('settings.team'))


@settings_bp.route('/team/<int:user_id>/role', methods=['POST'])
@login_required
@admin_required
def change_role(user_id):
    try:
        if user_id == current_user.id:
            flash("You can't change your own role.", 'error')
            return redirect(url_for('settings.team'))
        user = User.query.filter_by(
            id=user_id, tenant_id=current_user.tenant_id
        ).first_or_404()
        new_role = request.form.get('role')
        if new_role in [UserRole.ADMIN, UserRole.MEMBER]:
            user.role = new_role
            db.session.commit()
            flash(f'{user.full_name} is now {new_role}.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('change_role error uid=%d: %s', user_id, exc)
        flash('Could not update role.', 'error')
    return redirect(url_for('settings.team'))


# ================================================================
#  PROFILE  (any user)
# ================================================================
@settings_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        try:
            full_name    = request.form.get('full_name', '').strip()
            new_password = request.form.get('new_password', '').strip()
            confirm      = request.form.get('confirm_password', '').strip()
            current_pw   = request.form.get('current_password', '').strip()

            if not full_name:
                flash('Name is required.', 'error')
                return render_template('settings/profile.html')

            if not current_user.check_password(current_pw):
                flash('Current password is incorrect.', 'error')
                return render_template('settings/profile.html')

            current_user.full_name = full_name

            if new_password:
                if len(new_password) < 8:
                    flash('New password must be at least 8 characters.', 'error')
                    return render_template('settings/profile.html')
                if new_password != confirm:
                    flash('Passwords do not match.', 'error')
                    return render_template('settings/profile.html')
                current_user.set_password(new_password)
                flash('Password updated.', 'success')

            db.session.commit()
            flash('Profile saved.', 'success')
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception('Profile save error: %s', exc)
            flash('Failed to save profile.', 'error')
        return redirect(url_for('settings.profile'))

    return render_template('settings/profile.html')


# ================================================================
#  CAD PROFILES  (Phase 5)
# ================================================================
from ..models import CadProfile

@settings_bp.route('/cad')
@login_required
@admin_required
def cad():
    profiles = CadProfile.query.filter_by(
        tenant_id=current_user.tenant_id
    ).order_by(CadProfile.created_at).all()
    return render_template('settings/cad.html', profiles=profiles)


@settings_bp.route('/cad/seed', methods=['POST'])
@login_required
@admin_required
def seed_profile():
    """Seed the PWQ-3645 profile from our binary scan results."""
    try:
        tid = current_user.tenant_id
        existing = CadProfile.query.filter_by(
            tenant_id=tid, drawing_ref='PWQ-3645'
        ).first()
        if existing:
            flash('PWQ-3645 profile already exists.', 'info')
            return redirect(url_for('settings.cad'))

        profile = CadProfile(
            tenant_id        = tid,
            name             = 'PWQ-3645 Aluminium',
            drawing_ref      = 'PWQ-3645',
            material         = 'Aluminium',
            bar_width_mm     = 40.0,
            wall_thickness_mm= 4.0,
            depth_mm         = 52.0,
            glass_rebate_mm  = 20.0,
            weather_seal_mm  = 2.0,
            source_file      = 'PWQ-3645_v4_dwg_1_5301_1.dwg',
            is_default       = True,
        )
        db.session.add(profile)
        db.session.commit()
        current_app.logger.info('PWQ-3645 profile seeded for tenant=%d', tid)
        flash('PWQ-3645 profile seeded (bar=40mm, wall=4mm, depth=52mm).', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Seed profile error: %s', exc)
        flash('Failed to seed profile.', 'error')
    return redirect(url_for('settings.cad'))



@settings_bp.route('/cad/add', methods=['POST'])
@login_required
@admin_required
def add_profile():
    try:
        profile = CadProfile(
            tenant_id        = current_user.tenant_id,
            name             = request.form.get('name','').strip(),
            drawing_ref      = request.form.get('drawing_ref','').strip(),
            material         = request.form.get('material','Aluminium'),
            bar_width_mm     = float(request.form.get('bar_width_mm', 40)),
            wall_thickness_mm= float(request.form.get('wall_thickness_mm', 4)),
            depth_mm         = float(request.form.get('depth_mm', 52)),
        )
        db.session.add(profile)
        db.session.commit()
        flash(f'Profile "{profile.name}" added.', 'success')
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        flash(f'Invalid value: {exc}', 'error')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('add_profile error: %s', exc)
        flash('Failed to add profile.', 'error')
    return redirect(url_for('settings.cad'))


@settings_bp.route('/cad/<int:profile_id>/default', methods=['POST'])
@login_required
@admin_required
def set_default_profile(profile_id):
    try:
        # clear existing defaults
        CadProfile.query.filter_by(tenant_id=current_user.tenant_id).update(
            {'is_default': False})
        profile = CadProfile.query.filter_by(
            id=profile_id, tenant_id=current_user.tenant_id).first_or_404()
        profile.is_default = True
        db.session.commit()
        flash(f'"{profile.name}" set as default.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('set_default_profile error: %s', exc)
        flash('Could not update default.', 'error')
    return redirect(url_for('settings.cad'))


@settings_bp.route('/cad/<int:profile_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_profile(profile_id):
    try:
        profile = CadProfile.query.filter_by(
            id=profile_id, tenant_id=current_user.tenant_id).first_or_404()
        db.session.delete(profile)
        db.session.commit()
        flash('Profile deleted.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('delete_profile error: %s', exc)
        flash('Could not delete profile.', 'error')
    return redirect(url_for('settings.cad'))


# ================================================================
#  PROFILE LIBRARY  (PWQ-style: 16 profiles, 7 categories, DXF upload)
# ================================================================

from ..services.dxf_parser import process_dxf

PROFILE_CATEGORIES = ['Frame', 'Sash', 'Sill', 'GlazingBead', 'Mullion', 'Transom', 'Hardware']

# Directory containing the canonical profile section DXFs shipped with the app
CAD_SECTIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'cad_sections', 'cad_sections')

# Seed data — the six role-named DXFs that ship in app/cad_sections/cad_sections/.
# Dimensions are taken from the actual DXF geometry (verified by process_dxf) and
# are auto-corrected at seed time anyway. Every profile gets a `role` and
# `is_role_default=True` so frame_assembly.resolve_profiles() finds them
# immediately after seeding — no manual role assignment needed.
#   code, name, category, role, bar_w, depth, rebate_w, rebate_d, glass_rebate, dxf
BUILTIN_PROFILES = [
    # head/cill DXFs are vertical sections: bar = drawn HEIGHT, depth = drawn WIDTH
    ('HD-90',  'Head Frame 35×90',        'Frame',       'head',         35.0, 90.0, 18.0, 15.0, 18.0, 'head.dxf'),
    ('SL-165', 'Sill Frame 66×165',       'Sill',        'cill',         66.0,165.0,  0.0,  0.0,  0.0, 'sill.dxf'),
    ('JB-67',  'Jamb Frame 67×90',        'Frame',       'jamb',         67.0, 90.0, 18.0, 15.0, 18.0, 'jamb.dxf'),
    ('GB-61',  'Glazing Bar 61×58',       'Mullion',     'mullion',      61.2, 58.0, 15.0, 12.0,  0.0, 'glazing_bar.dxf'),
    ('MS-85',  'Meeting Stile 85×27',     'Sash',        'meeting_stile',85.0, 27.0, 15.0, 12.0,  0.0, 'meeting_stile.dxf'),
    ('BD-58',  'Glazing Bead 58×65',      'GlazingBead', 'glazing_bead', 58.0, 65.0,  0.0,  0.0, 20.0, 'bead.dxf'),
]

# The glazing bar doubles as the transom (same section rotated 90° at build
# time by the assembly engine), so we also mark it transom-default in the seed.
_EXTRA_ROLE_DEFAULTS = {'GB-61': 'transom'}


@settings_bp.route('/profiles')
@login_required
@admin_required
def profiles_library():
    cat_filter = request.args.get('category', '')
    q = CadProfile.query.filter_by(tenant_id=current_user.tenant_id)
    if cat_filter:
        q = q.filter_by(category=cat_filter)
    profiles = q.order_by(CadProfile.category, CadProfile.code).all()
    total = CadProfile.query.filter_by(tenant_id=current_user.tenant_id).count()
    return render_template('settings/profiles_library.html',
                           profiles=profiles,
                           total=total,
                           categories=PROFILE_CATEGORIES,
                           active_cat=cat_filter)


@settings_bp.route('/profiles/seed', methods=['POST'])
@login_required
@admin_required
def seed_profiles():
    """
    Seed the built-in profiles from app/cad_sections/cad_sections/.
    Unlike the old seed, this:
      * assigns `role` + `is_role_default=True` so frame_assembly's
        resolve_profiles() finds them immediately (no manual role step)
      * runs process_dxf on the shipped DXF so geometry_json / svg_path
        are populated — the 3D builder sweeps the real chambered section
        instead of a plain rectangle
      * auto-corrects bar/depth from the actual DXF geometry
    Skips any profile whose code already exists. Re-running fills gaps.
    """
    tid = current_user.tenant_id
    created, geo_loaded = 0, 0
    for (code, name, cat, role, bar_w, depth,
         reb_w, reb_d, glass_r, dxf_file) in BUILTIN_PROFILES:
        if CadProfile.query.filter_by(tenant_id=tid, code=code).first():
            continue
        p = CadProfile(
            tenant_id       = tid,
            code            = code,
            name            = name,
            category        = cat,
            role            = role,
            is_role_default = True,
            bar_width_mm    = bar_w,
            depth_mm        = depth,
            rebate_w_mm     = reb_w,
            rebate_d_mm     = reb_d,
            glass_rebate_mm = glass_r,
            drawing_ref     = 'cad_sections',
            material        = 'Aluminium',
            is_builtin      = True,
            source_file     = dxf_file,
        )
        # Load the shipped DXF geometry so 3D + section drawings use the
        # real profile from day one.
        dxf_path = os.path.join(CAD_SECTIONS_DIR, dxf_file)
        if os.path.exists(dxf_path):
            try:
                content = open(dxf_path, encoding='utf-8',
                                errors='replace').read()
                result = process_dxf(content)
                if result.get('ok'):
                    p.geometry_json = result['geometry_json']
                    p.svg_path      = result['svg_path']
                    p.vertex_count  = result['vertex_count']
                    p.bar_width_mm, p.depth_mm = _role_aware_dims(role, result)
                    geo_loaded += 1
                else:
                    current_app.logger.warning(
                        'seed: DXF parse failed for %s: %s',
                        dxf_file, result.get('error'))
            except Exception as exc:
                current_app.logger.warning(
                    'seed: could not load %s: %s', dxf_file, exc)
        else:
            current_app.logger.warning(
                'seed: DXF not found on disk: %s', dxf_path)
        db.session.add(p)
        created += 1
    db.session.commit()

    # Secondary role defaults (e.g. the glazing bar also serves as transom).
    # A separate DB row per extra role keeps is_role_default semantics simple.
    for code, extra_role in _EXTRA_ROLE_DEFAULTS.items():
        src = CadProfile.query.filter_by(tenant_id=tid, code=code).first()
        already = CadProfile.query.filter_by(
            tenant_id=tid, role=extra_role, is_role_default=True).first()
        if src and not already:
            dup = CadProfile(
                tenant_id       = tid,
                code            = f'{code}-T',
                name            = f'{src.name} (as {extra_role})',
                category        = 'Transom',
                role            = extra_role,
                is_role_default = True,
                bar_width_mm    = src.bar_width_mm,
                depth_mm        = src.depth_mm,
                rebate_w_mm     = src.rebate_w_mm,
                rebate_d_mm     = src.rebate_d_mm,
                glass_rebate_mm = src.glass_rebate_mm,
                drawing_ref     = src.drawing_ref,
                material        = src.material,
                is_builtin      = True,
                source_file     = src.source_file,
                geometry_json   = src.geometry_json,
                svg_path        = src.svg_path,
                vertex_count    = src.vertex_count,
            )
            db.session.add(dup)
            created += 1
    db.session.commit()

    flash(f'{created} profile(s) seeded, {geo_loaded} with DXF geometry '
          f'and roles pre-assigned. 3D assembly is ready to use.', 'success')
    return redirect(url_for('settings.profiles_library'))


# Maps a profile's role (or code) to the canonical DXF that ships with the app,
# so we can backfill geometry even when source_file points at an old filename.
_ROLE_TO_DXF = {
    'head':          'head.dxf',
    'cill':          'sill.dxf',
    'jamb':          'jamb.dxf',
    'mullion':       'glazing_bar.dxf',
    'transom':       'glazing_bar.dxf',
    'sash':          'meeting_stile.dxf',
    'meeting_stile': 'meeting_stile.dxf',
    'glazing_bead':  'bead.dxf',
}

# Cills/heads are drawn as VERTICAL sections in the DXFs: X-span = through-wall
# depth, Y-span = elevation face height (bar). Jambs/mullions are drawn in plan
# (X = bar). Without this swap the sill stands 165 mm upright instead of lying
# 165 mm deep — see PWQ-3645 side section.
_DEPTH_ALONG_X_ROLES = ('head', 'cill', 'threshold')

def _role_aware_dims(role, result):
    """Return (bar_mm, depth_mm) for a parsed DXF given the member role."""
    w, h = result['width_mm'], result['height_mm']
    if role in _DEPTH_ALONG_X_ROLES:
        return h, w          # bar = drawn height, depth = drawn width
    return w, h



@settings_bp.route('/profiles/backfill-geometry', methods=['POST'])
@login_required
@admin_required
def backfill_geometry():
    """
    Make every profile usable by the 3D assembly in one click:
      1. Load DXF geometry into any profile missing it (so the real shape
         is extruded instead of a plain box).
      2. Assign a `role` + `is_role_default` to any profile that has none,
         inferred from its category, so frame_assembly can place it.

    Both steps are needed: geometry alone still renders boxes if the profile
    has no role, because resolve_profiles selects strictly by role.
    """
    tid = current_user.tenant_id
    profiles = CadProfile.query.filter_by(tenant_id=tid).all()
    filled, roles_set, missing = 0, 0, []

    # ── 1. Geometry backfill ──────────────────────────────────────────
    for p in profiles:
        if p.geometry_json:
            pass  # keep existing geometry
        else:
            candidates = []
            if p.source_file:
                candidates.append(p.source_file)
            if p.role and p.role in _ROLE_TO_DXF:
                candidates.append(_ROLE_TO_DXF[p.role])
            dxf_path = None
            for c in candidates:
                cand = os.path.join(CAD_SECTIONS_DIR, os.path.basename(c))
                if os.path.exists(cand):
                    dxf_path = cand
                    break
            if dxf_path:
                try:
                    content = open(dxf_path, encoding='utf-8', errors='replace').read()
                    result  = process_dxf(content)
                    if result.get('ok'):
                        p.geometry_json = result['geometry_json']
                        p.svg_path      = result['svg_path']
                        p.vertex_count  = result['vertex_count']
                        p.bar_width_mm, p.depth_mm = _role_aware_dims(p.role, result)
                        p.source_file   = os.path.basename(dxf_path)
                        filled += 1
                except Exception as exc:
                    current_app.logger.warning('backfill geom %s: %s', p.code, exc)

    # ── 2. Role backfill from category ────────────────────────────────
    # Category → role. 'Frame' is ambiguous (head vs jamb) so we use it for
    # head, and reuse the same profile for jamb only if no dedicated jamb exists.
    cat_to_role = {
        'Sill':        'cill',
        'Mullion':     'mullion',
        'Transom':     'transom',
        'Sash':        'sash',
        'GlazingBead': 'glazing_bead',
        # 'Frame' handled specially below
        # 'Hardware' has no frame role — skipped
    }
    # Track which roles already have a default so we set exactly one per role
    have_default = set()
    for p in profiles:
        if p.role and p.is_role_default:
            have_default.add(p.role)

    # First pass: non-Frame categories
    for p in profiles:
        if p.role:
            continue
        role = cat_to_role.get(p.category)
        if role:
            p.role = role
            if role not in have_default:
                p.is_role_default = True
                have_default.add(role)
            roles_set += 1

    # Frame category → head (and jamb if none set)
    frame_profiles = [p for p in profiles
                      if p.category == 'Frame' and (p.role in (None, 'head', 'jamb'))]
    for p in frame_profiles:
        if not p.role:
            p.role = 'head'
            roles_set += 1
        if p.role == 'head' and 'head' not in have_default:
            p.is_role_default = True
            have_default.add('head')

    # Ensure a jamb default exists — reuse the head-default profile if not
    if 'jamb' not in have_default:
        head_def = next((p for p in profiles
                         if p.role == 'head' and p.is_role_default), None)
        if head_def:
            # create a jamb clone pointing at the same geometry
            jamb = CadProfile(
                tenant_id=tid, code=f'{head_def.code}-JAMB',
                name=f'{head_def.name} (as jamb)', category='Frame',
                role='jamb', is_role_default=True,
                bar_width_mm=head_def.bar_width_mm, depth_mm=head_def.depth_mm,
                rebate_w_mm=head_def.rebate_w_mm, rebate_d_mm=head_def.rebate_d_mm,
                glass_rebate_mm=head_def.glass_rebate_mm,
                material=head_def.material, is_builtin=True,
                source_file=head_def.source_file,
                geometry_json=head_def.geometry_json, svg_path=head_def.svg_path,
                vertex_count=head_def.vertex_count)
            db.session.add(jamb)
            have_default.add('jamb')
            roles_set += 1

    db.session.commit()

    covered = ', '.join(sorted(have_default)) or 'none'
    flash(f'Geometry loaded into {filled} profile(s); roles assigned to '
          f'{roles_set} profile(s). Roles now covered: {covered}. '
          f'Open a window in 3D to see the real profiles.', 'success')
    return redirect(url_for('settings.profiles_library'))


@settings_bp.route('/profiles/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_profile():
    if request.method == 'POST':
        try:
            p = CadProfile(
                tenant_id       = current_user.tenant_id,
                code            = request.form.get('code','').strip().upper(),
                name            = request.form.get('name','').strip(),
                category        = request.form.get('category','Frame'),
                bar_width_mm    = float(request.form.get('bar_width_mm', 60)),
                depth_mm        = float(request.form.get('depth_mm', 90)),
                rebate_w_mm     = float(request.form.get('rebate_w_mm', 0)),
                rebate_d_mm     = float(request.form.get('rebate_d_mm', 0)),
                glass_rebate_mm = float(request.form.get('glass_rebate_mm', 0)),
                material        = request.form.get('material','Aluminium'),
                drawing_ref     = request.form.get('drawing_ref','').strip(),
                is_builtin      = False,
            )
            db.session.add(p)
            db.session.commit()
            flash(f'Profile {p.code} created.', 'success')
            return redirect(url_for('settings.profiles_library'))
        except Exception as exc:
            db.session.rollback()
            flash(f'Error: {exc}', 'error')
    return render_template('settings/profile_create.html',
                           categories=PROFILE_CATEGORIES)


@settings_bp.route('/profiles/<int:profile_id>/upload-dxf', methods=['GET', 'POST'])
@login_required
@admin_required
def upload_dxf(profile_id):
    profile = CadProfile.query.filter_by(
        id=profile_id, tenant_id=current_user.tenant_id).first_or_404()

    if request.method == 'POST':
        f = request.files.get('dxf_file')
        if not f or not f.filename.lower().endswith('.dxf'):
            flash('Please upload a .dxf file.', 'error')
            return render_template('settings/upload_dxf.html', profile=profile)
        try:
            content = f.read().decode('utf-8', errors='replace')
            result  = process_dxf(content)
            if not result['ok']:
                flash(f'DXF parse error: {result["error"]}', 'error')
                return render_template('settings/upload_dxf.html', profile=profile)

            profile.geometry_json = result['geometry_json']
            profile.svg_path      = result['svg_path']
            profile.vertex_count  = result['vertex_count']
            profile.source_file   = f.filename
            # Auto-update dimensions from actual DXF
            profile.bar_width_mm, profile.depth_mm = _role_aware_dims(
                profile.role, result)
            db.session.commit()
            flash(f'DXF geometry saved: {result["vertex_count"]} vertices, '
                  f'{result["width_mm"]}×{result["height_mm"]}mm', 'success')
            return redirect(url_for('settings.profiles_library'))
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception('upload_dxf error: %s', exc)
            flash(f'Upload failed: {exc}', 'error')

    return render_template('settings/upload_dxf.html', profile=profile)


@settings_bp.route('/profiles/<int:profile_id>/clear-geometry', methods=['POST'])
@login_required
@admin_required
def clear_geometry(profile_id):
    profile = CadProfile.query.filter_by(
        id=profile_id, tenant_id=current_user.tenant_id).first_or_404()
    profile.geometry_json = None
    profile.svg_path      = None
    profile.vertex_count  = None
    db.session.commit()
    flash('Geometry removed.', 'success')
    return redirect(url_for('settings.upload_dxf', profile_id=profile_id))


@settings_bp.route('/profiles/<int:profile_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_profile_library(profile_id):
    profile = CadProfile.query.filter_by(
        id=profile_id, tenant_id=current_user.tenant_id).first_or_404()
    db.session.delete(profile)
    db.session.commit()
    flash('Profile deleted.', 'success')
    return redirect(url_for('settings.profiles_library'))


_VALID_ROLES = [
    'outer_frame', 'head', 'cill', 'jamb', 'mullion', 'transom',
    'sash', 'glazing_bead', 'threshold', 'coupler',
    'door_leaf', 'meeting_stile',
]


@settings_bp.route('/profiles/<int:profile_id>/role', methods=['POST'])
@login_required
@admin_required
def set_profile_role(profile_id):
    """Assign a 3D assembly role to a profile (drives frame_assembly + 3D builder)."""
    profile = CadProfile.query.filter_by(
        id=profile_id, tenant_id=current_user.tenant_id).first_or_404()
    role = (request.form.get('role') or '').strip() or None
    if role and role not in _VALID_ROLES:
        flash(f'Unknown role: {role}', 'error')
        return redirect(url_for('settings.profiles_library'))
    profile.role = role
    make_default = bool(request.form.get('is_role_default'))
    if make_default and role:
        CadProfile.query.filter_by(
            tenant_id=current_user.tenant_id, role=role,
            material=profile.material
        ).update({'is_role_default': False})
        profile.is_role_default = True
    elif not make_default:
        profile.is_role_default = False
    db.session.commit()
    flash(
        f'{profile.code or profile.name} → role '
        f'"{role or "none"}"'
        f'{" (default)" if profile.is_role_default else ""}.',
        'success'
    )
    return redirect(url_for('settings.profiles_library'))


# ================================================================
#  GLASS UNIT LIBRARY
# ================================================================

from ..models.glass_unit import GlassUnit

BUILTIN_GLASS = [
    # code, name, build_up, thickness_mm, u_value, g_value, description, sort, price_per_m2
    ('SG-4',  'Single Glazed 4mm',           '4',          4.0,  5.8,  0.87, 'Basic single pane. No thermal performance.', 1, 42.00),
    ('DG-24', 'Double Glazed 4/16/4',        '4/16/4',    24.0,  1.4,  0.63, 'Standard double glazing with 16mm air gap.', 2, 68.00),
    ('DG-28', 'Double Glazed 4/20/4 Low-E',  '4/20/4',    28.0,  1.2,  0.60, 'Low-E coating on pane 2. Improved thermal retention.', 3, 82.00),
    ('DG-32', 'Double Glazed 6/20/6 Low-E',  '6/20/6',    32.0,  1.1,  0.58, 'Thicker glass for improved acoustic and thermal.', 4, 95.00),
    ('DG-36', 'Double Glazed 6/24/6 Low-E',  '6/24/6',    36.0,  1.0,  0.57, 'Optimal double-glazing spec. Meets Part L.', 5, 108.00),
    ('TG-40', 'Triple Glazed 4/14/4/14/4',   '4/14/4/14/4', 40.0, 0.7, 0.50, 'Triple glazing. Passive house suitable.', 6, 135.00),
    ('TG-44', 'Triple Glazed 4/16/4/16/4',   '4/16/4/16/4', 44.0, 0.65, 0.48, 'Enhanced triple glazing. Argon filled.', 7, 152.00),
    ('TG-48', 'Triple Glazed 4/18/4/18/4',   '4/18/4/18/4', 48.0, 0.6, 0.46, 'Premium triple glazing with Krypton fill.', 8, 178.00),
    ('OB-6',  'Obscure 6mm',                 '6',           6.0, None, None,  'Patterned/frosted single pane. Privacy glass.', 9, 55.00),
    ('AC-44', 'Acoustic 6/12/6 Laminated',   '6/12/6.4',   44.0,  1.3,  0.60, 'Laminated inner pane. Rw 42dB. For road/rail noise.', 10, 128.00),
    ('SC-28', 'Solar Control 4/16/4',        '4/16/4',     28.0,  1.3,  0.35, 'Solar control coating. Reduces summer heat gain.', 11, 115.00),
    ('SF-32', 'Safety + Fire 6/20/6',        '6/20/6',     32.0,  1.1,  0.60, 'Toughened + intumescent interlayer. FD30 rated.', 12, 165.00),
]


@settings_bp.route('/glass')
@login_required
@admin_required
def glass_library():
    units = GlassUnit.query.filter_by(
        tenant_id=current_user.tenant_id
    ).order_by(GlassUnit.sort_order, GlassUnit.code).all()
    return render_template('settings/glass_library.html',
                           units=units,
                           total=len(units))


@settings_bp.route('/glass/seed', methods=['POST'])
@login_required
@admin_required
def seed_glass():
    tid = current_user.tenant_id
    created = 0
    for sort, (code, name, build_up, thick, u_val, g_val, desc, s, price) in enumerate(BUILTIN_GLASS):
        if GlassUnit.query.filter_by(tenant_id=tid, code=code).first():
            continue
        db.session.add(GlassUnit(
            tenant_id=tid, code=code, name=name,
            build_up=build_up, thickness_mm=thick,
            u_value=u_val, g_value=g_val, price_per_m2=price,
            description=desc, is_builtin=True, sort_order=s
        ))
        created += 1
    db.session.commit()
    flash(f'{created} glass unit(s) seeded.', 'success')
    return redirect(url_for('settings.glass_library'))


@settings_bp.route('/glass/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_glass():
    if request.method == 'POST':
        try:
            u_val = request.form.get('u_value','').strip()
            g_val = request.form.get('g_value','').strip()
            price = request.form.get('price_per_m2','').strip()
            unit = GlassUnit(
                tenant_id    = current_user.tenant_id,
                code         = request.form.get('code','').strip().upper(),
                name         = request.form.get('name','').strip(),
                build_up     = request.form.get('build_up','').strip(),
                thickness_mm = float(request.form.get('thickness_mm', 24)),
                u_value      = float(u_val) if u_val else None,
                g_value      = float(g_val) if g_val else None,
                price_per_m2 = float(price) if price else None,
                description  = request.form.get('description','').strip(),
                is_builtin   = False,
                sort_order   = 99,
            )
            db.session.add(unit)
            db.session.commit()
            flash(f'Glass unit {unit.code} created.', 'success')
            return redirect(url_for('settings.glass_library'))
        except Exception as exc:
            db.session.rollback()
            flash(f'Error: {exc}', 'error')
    return render_template('settings/glass_create.html')


@settings_bp.route('/glass/<int:unit_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_glass(unit_id):
    unit = GlassUnit.query.filter_by(
        id=unit_id, tenant_id=current_user.tenant_id).first_or_404()
    db.session.delete(unit)
    db.session.commit()
    flash('Glass unit deleted.', 'success')
    return redirect(url_for('settings.glass_library'))

# ────────────────────────────────────────────────────────────────────
#  Profile Systems  (full named assembly system: window + door)
# ────────────────────────────────────────────────────────────────────
@settings_bp.route('/profile-systems')
@login_required
@admin_required
def profile_systems():
    from ..models.profile_system import ProfileSystem
    from ..models.cad_profile import CadProfile
    systems  = ProfileSystem.query.filter_by(
        tenant_id=current_user.tenant_id).order_by(ProfileSystem.name).all()
    profiles = CadProfile.query.filter_by(
        tenant_id=current_user.tenant_id, is_active=True
    ).order_by(CadProfile.category, CadProfile.code).all()
    return render_template('settings/profile_systems.html',
                           systems=systems, profiles=profiles)


@settings_bp.route('/profile-systems/new', methods=['POST'])
@login_required
@admin_required
def create_profile_system():
    from ..models.profile_system import ProfileSystem
    name = request.form.get('name', '').strip()
    if not name:
        flash('Name is required.', 'error')
        return redirect(url_for('settings.profile_systems'))
    sys = ProfileSystem(
        tenant_id=current_user.tenant_id,
        name=name,
        material=request.form.get('material', 'Aluminium'),
        notes=request.form.get('notes', '').strip() or None,
    )
    db.session.add(sys)
    db.session.commit()
    flash(f'System "{name}" created.', 'success')
    return redirect(url_for('settings.edit_profile_system', system_id=sys.id))


@settings_bp.route('/profile-systems/<int:system_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_profile_system(system_id):
    from ..models.profile_system import ProfileSystem
    from ..models.cad_profile import CadProfile
    sys = ProfileSystem.query.filter_by(
        id=system_id, tenant_id=current_user.tenant_id).first_or_404()
    profiles = CadProfile.query.filter_by(
        tenant_id=current_user.tenant_id, is_active=True
    ).order_by(CadProfile.category, CadProfile.code).all()

    if request.method == 'POST':
        sys.name     = request.form.get('name', sys.name).strip()
        sys.material = request.form.get('material', sys.material)
        sys.notes    = request.form.get('notes', '').strip() or None
        sys.frame_corner_joint = request.form.get('frame_corner_joint', 'mitre_45')
        sys.sash_corner_joint  = request.form.get('sash_corner_joint',  'mitre_45')
        sys.internal_joint     = request.form.get('internal_joint',     'butt')
        try:
            sys.sash_clearance_mm = float(request.form.get('sash_clearance_mm', 2.0))
        except ValueError:
            pass
        # Update every slot (set to None if not supplied)
        for slot in ProfileSystem.SLOTS:
            fk_col = f'{slot}_id'
            val = request.form.get(slot) or None
            setattr(sys, fk_col, int(val) if val else None)
        db.session.commit()
        flash('Profile system saved.', 'success')
        return redirect(url_for('settings.edit_profile_system', system_id=sys.id))

    return render_template('settings/profile_system_edit.html',
                           sys=sys, profiles=profiles,
                           ProfileSystem=ProfileSystem)


@settings_bp.route('/profile-systems/<int:system_id>/default', methods=['POST'])
@login_required
@admin_required
def set_default_profile_system(system_id):
    from ..models.profile_system import ProfileSystem
    ProfileSystem.query.filter_by(
        tenant_id=current_user.tenant_id).update({'is_default': False})
    sys = ProfileSystem.query.filter_by(
        id=system_id, tenant_id=current_user.tenant_id).first_or_404()
    sys.is_default = True
    db.session.commit()
    flash(f'"{sys.name}" is now the default system.', 'success')
    return redirect(url_for('settings.profile_systems'))


@settings_bp.route('/profile-systems/<int:system_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_profile_system(system_id):
    from ..models.profile_system import ProfileSystem
    sys = ProfileSystem.query.filter_by(
        id=system_id, tenant_id=current_user.tenant_id).first_or_404()
    db.session.delete(sys)
    db.session.commit()
    flash('Profile system deleted.', 'success')
    return redirect(url_for('settings.profile_systems'))