from ..extensions import db
from ..models import Interaction


def get_by_id(tenant_id: int, interaction_id: int):
    return Interaction.query.filter_by(tenant_id=tenant_id, id=interaction_id).first()


def list_for_lead(tenant_id: int, lead_id: int):
    return (Interaction.query
            .filter_by(tenant_id=tenant_id, lead_id=lead_id)
            .order_by(Interaction.created_at.desc())
            .all())


def create(tenant_id: int, **fields) -> Interaction:
    interaction = Interaction(tenant_id=tenant_id, **fields)
    db.session.add(interaction)
    db.session.flush()
    return interaction


def update(interaction: Interaction, **fields) -> Interaction:
    for key, value in fields.items():
        if hasattr(interaction, key):
            setattr(interaction, key, value)
    db.session.flush()
    return interaction


def delete(interaction: Interaction) -> None:
    db.session.delete(interaction)
    db.session.flush()
