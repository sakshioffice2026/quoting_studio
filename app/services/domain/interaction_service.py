from ...extensions import db
from ...repositories import interaction_repo, lead_repo
from ...models.interaction import InteractionType, InteractionOutcome, QualificationScore
from ...models.lead import FollowUpStatus

def list_interactions(tenant_id: int, lead_id: int):
    return interaction_repo.list_for_lead(tenant_id, lead_id)


def log_interaction(tenant_id: int, lead_id: int, interaction_type: str, created_by: int = None,
                     outcome: str = None, notes: str = None, next_action_date=None,
                     qualification_score: str = None, lost_reason: str = None):
    if interaction_type not in InteractionType.ALL:
        raise ValueError(f'Invalid interaction_type: {interaction_type}')
    if outcome and outcome not in InteractionOutcome.ALL:
        raise ValueError(f'Invalid outcome: {outcome}')
    if qualification_score and qualification_score not in QualificationScore.ALL:
        raise ValueError(f'Invalid qualification_score: {qualification_score}')

    lead = lead_repo.get_by_id(tenant_id, lead_id)
    if not lead:
        raise LookupError('Lead not found')

    interaction = interaction_repo.create(
        tenant_id=tenant_id,
        lead_id=lead_id,
        created_by=created_by,
        interaction_type=interaction_type,
        outcome=outcome,
        notes=notes,
        next_action_date=next_action_date,
        qualification_score=qualification_score,
        lost_reason=lost_reason,
    )

    # Keep Lead.follow_up_status in sync with the latest touchpoint outcome.
    # NOTE: FUP-QUALIFIED is only ever set via the explicit qualify_lead() gate
    # (Section 2 approval gate), since that path also creates/dedupes the
    # Customer record. A "Hot" score here is a signal for the sales exec, not
    # itself a qualification event, so it must not bypass that gate.
    if outcome == InteractionOutcome.NOT_INTERESTED:
        lead.follow_up_status = FollowUpStatus.LOST
        lead.lost_reason = lost_reason or 'Not interested'
    elif lead.follow_up_status in (None, FollowUpStatus.NURTURE):
        lead.follow_up_status = FollowUpStatus.IN_PROGRESS

    db.session.commit()
    return interaction


def delete_interaction(tenant_id: int, interaction_id: int):
    interaction = interaction_repo.get_by_id(tenant_id, interaction_id)
    if not interaction:
        raise LookupError('Interaction not found')
    interaction_repo.delete(interaction)
    db.session.commit()
