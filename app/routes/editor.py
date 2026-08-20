from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from ..models import Project, Window
from ..models.glass_unit import GlassUnit

editor_bp = Blueprint('editor', __name__)

@editor_bp.route('/projects/<int:project_id>/windows/<int:window_id>/edit')
@login_required
def edit(project_id, window_id):
    project = Project.query.filter_by(
        id=project_id, tenant_id=current_user.tenant_id
    ).first_or_404()
    window = Window.query.filter_by(
        id=window_id, tenant_id=current_user.tenant_id
    ).first_or_404()

    # all windows for Save & Next / window counter
    all_windows = project.windows.order_by(Window.sequence_order).all()
    current_idx = next((i for i, w in enumerate(all_windows) if w.id == window_id), 0)
    next_window = all_windows[current_idx + 1] if current_idx + 1 < len(all_windows) else None
    prev_window = all_windows[current_idx - 1] if current_idx > 0 else None

    # Pass glass library to editor for the Glass tab dropdown
    glass_units = GlassUnit.query.filter_by(
        tenant_id=current_user.tenant_id, is_active=True
    ).order_by(GlassUnit.sort_order, GlassUnit.code).all()

    # Pass CadProfile library for the Profiles tab
    from ..models.cad_profile import CadProfile
    cad_profiles = CadProfile.query.filter_by(
        tenant_id=current_user.tenant_id, is_active=True
    ).order_by(CadProfile.category, CadProfile.code).all()

    from ..models.profile_system import ProfileSystem
    profile_systems = ProfileSystem.query.filter_by(
        tenant_id=current_user.tenant_id, is_active=True
    ).order_by(ProfileSystem.name).all()

    return render_template('editor.html',
                           project=project,
                           window=window,
                           all_windows=all_windows,
                           current_idx=current_idx,
                           next_window=next_window,
                           prev_window=prev_window,
                           design_json=getattr(window, "design_json", None),
                           glass_units=[u.to_dict() for u in glass_units],
                           cad_profiles=[p.to_dict() for p in cad_profiles],
                           profile_systems=[s.to_dict() for s in profile_systems],
                           current_system_id=getattr(window, 'profile_system_id', None))