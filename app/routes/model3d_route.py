from flask import Blueprint, render_template
from flask_login import login_required, current_user
from ..models import Project, Window

model3d_bp = Blueprint('model3d', __name__)

@model3d_bp.route('/projects/<int:project_id>/windows/<int:window_id>/3d')
@login_required
def view(project_id, window_id):
    project = Project.query.filter_by(
        id=project_id, tenant_id=current_user.tenant_id).first_or_404()
    window = Window.query.filter_by(
        id=window_id, tenant_id=current_user.tenant_id).first_or_404()
    return render_template('model3d.html', project=project, window=window)
