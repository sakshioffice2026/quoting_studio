"""
Master Acceptance — one customer action instead of many approvals.

A single "Approve & Proceed" on the Master Quotation page:

  1. approves every visual item
  2. approves the design (locks windows for manufacturing)
  3. accepts the quotation
  4. creates + confirms the order
  5. raises the Advance invoice (payment stage 1)

Later payment stages are raised automatically by
payment_service.auto_invoice_stages as manufacturing, delivery and
installation progress, so the customer never has to approve again.

Every step is idempotent: calling accept_everything() again on a
partly-finished quotation only completes the missing steps.
"""
import re
from datetime import date
from decimal import Decimal

from ...models.quotation import Quotation, QuotationStatus
from ...models.design_approval import DesignApprovalStatus
from ...models.order import OrderStatus
from ...models.payment import PaymentStage

CONFIRMATION_METHOD = 'master_quote'

STAGE_TRIGGERS = {
    PaymentStage.ADVANCE:         'Paid when you approve — starts manufacturing',
    PaymentStage.PRE_DISPATCH:    'Due when manufacturing is complete, before dispatch',
    PaymentStage.ON_INSTALLATION: 'Due when your order is delivered',
    PaymentStage.RETENTION:       'Due after installation is complete',
}


def _advance_pct(quotation: Quotation, override=None) -> Decimal:
    """Advance % from override, else first '%' figure in payment terms, else default."""
    from . import payment_service

    if override is not None:
        try:
            pct = Decimal(str(override))
            if Decimal('0') < pct <= Decimal('100'):
                return pct
        except Exception:
            pass

    terms = quotation.payment_terms_template or ''
    match = re.search(r'(\d{1,3}(?:\.\d+)?)\s*%', terms)
    if match:
        try:
            pct = Decimal(match.group(1))
            if Decimal('0') < pct <= Decimal('100'):
                return pct
        except Exception:
            pass
    return payment_service.DEFAULT_ADVANCE_PCT


def payment_plan(quotation: Quotation, advance_pct=None) -> dict:
    """Full payment schedule, available before acceptance so the customer
    sees every stage up front. Percentages always sum to 100."""
    from . import payment_service

    pct_map = payment_service.stage_percentages(_advance_pct(quotation, advance_pct))
    total = Decimal(str(quotation.grand_total or 0))

    stages = []
    running = Decimal('0')
    order = PaymentStage.ALL
    for index, stage in enumerate(order):
        pct = pct_map[stage]
        if index == len(order) - 1:
            amount = total - running
        else:
            amount = (total * pct / Decimal('100')).quantize(Decimal('0.01'))
            running += amount
        stages.append({
            'stage':   stage,
            'label':   PaymentStage.LABELS.get(stage, stage),
            'percent': float(pct),
            'amount':  float(amount),
            'trigger': STAGE_TRIGGERS.get(stage, ''),
        })

    return {
        'stages':      stages,
        'total':       float(total),
        'advance_pct': float(pct_map[PaymentStage.ADVANCE]),
        'advance':     stages[0]['amount'] if stages else 0.0,
    }


def design_status(tenant_id: int, quotation: Quotation) -> dict:
    """Design approval state for the project, for display on the master page."""
    from . import design_approval_service

    approval = design_approval_service.get_latest_for_project(
        tenant_id, quotation.project_id)
    if not approval:
        return {'exists': False, 'approved': False, 'pending': False,
                'revision': None, 'approval_id': None}
    return {
        'exists':      True,
        'approved':    approval.status == DesignApprovalStatus.APPROVED,
        'pending':     approval.status in (DesignApprovalStatus.APPROVAL_SENT,
                                           DesignApprovalStatus.SUBMITTED),
        'revision':    approval.revision_number,
        'approval_id': approval.id,
        'status':      approval.status,
    }


def _step_visuals(tenant_id: int, quotation: Quotation, share_link, name: str) -> None:
    from . import visual_feedback_service

    state = visual_feedback_service.summary(tenant_id, quotation.id)
    if state.get('open_count'):
        raise ValueError(
            'There are open change requests. Please wait for our update '
            'before approving everything.')
    if state.get('all_approved'):
        return
    visual_feedback_service.approve_all(
        tenant_id, quotation.id, share_link=share_link, author_name=name)


def _step_design(tenant_id: int, quotation: Quotation, name: str) -> None:
    from . import design_approval_service

    approval = design_approval_service.get_latest_for_project(
        tenant_id, quotation.project_id)
    if approval is None or approval.status == DesignApprovalStatus.APPROVED:
        return
    if approval.status not in (DesignApprovalStatus.APPROVAL_SENT,
                               DesignApprovalStatus.SUBMITTED):
        raise ValueError(
            'The design is being revised. Please wait for the updated design '
            'before approving.')
    design_approval_service.approve(
        tenant_id, approval.id, approved_by=None,
        customer_signoff_notes=f'Approved online via Master Quotation by {name}')


def _step_quotation(tenant_id: int, quotation: Quotation, name: str) -> Quotation:
    from . import quotation_service

    if quotation.status == QuotationStatus.ACCEPTED:
        return quotation
    return quotation_service.accept_quotation(
        tenant_id=tenant_id,
        quotation_id=quotation.id,
        acceptance_method='portal',
        accepted_by_name=name,
    )


def _step_order(tenant_id: int, quotation: Quotation, name: str):
    from . import order_service

    order = order_service.get_for_quotation(tenant_id, quotation.id)
    if order is None:
        order = order_service.create_order(
            tenant_id=tenant_id,
            quotation_id=quotation.id,
            created_by=quotation.sent_by or quotation.prepared_by,
        )
    if order.status == OrderStatus.PENDING_SIGNATURE:
        order = order_service.confirm_order(
            tenant_id=tenant_id,
            order_id=order.id,
            order_confirmed_by_name=name,
            confirmation_method=CONFIRMATION_METHOD,
        )
    return order


def _step_advance(tenant_id: int, quotation: Quotation, order, advance_pct):
    from . import payment_service

    existing = payment_service.get_advance_for_order(tenant_id, order.id)
    if existing is not None:
        return existing
    return payment_service.raise_invoice(
        tenant_id=tenant_id,
        order_id=order.id,
        raised_by=quotation.sent_by or quotation.prepared_by,
        payment_stage=PaymentStage.ADVANCE,
        invoice_amount=0.0,
        due_date=date.today(),
        advance_pct=float(_advance_pct(quotation, advance_pct)),
    )


def accept_everything(
    tenant_id: int,
    quotation_id: int,
    accepted_by_name: str,
    share_link=None,
    advance_pct=None,
) -> dict:
    """Run the whole one-click approval. Raises ValueError / LookupError with a
    customer-safe message when a step cannot proceed."""
    from . import quotation_service

    name = (accepted_by_name or '').strip()
    if not name:
        raise ValueError('Please enter your full name to approve and proceed.')

    quotation = quotation_service.get_quotation(tenant_id, quotation_id)
    if not quotation:
        raise LookupError('Quotation not found')
    if quotation.status == QuotationStatus.ACCEPTED:
        pass
    elif quotation.status not in (QuotationStatus.SENT, QuotationStatus.NEGOTIATION):
        raise ValueError('This quotation is no longer open for approval.')
    elif quotation.is_expired:
        raise ValueError('This quotation has expired. Please contact us for an updated one.')

    # Validate the customer-facing blockers first so nothing is half-done.
    _step_visuals_check(tenant_id, quotation)

    _step_visuals(tenant_id, quotation, share_link, name)
    _step_design(tenant_id, quotation, name)
    quotation = _step_quotation(tenant_id, quotation, name)
    order = _step_order(tenant_id, quotation, name)
    advance = _step_advance(tenant_id, quotation, order, advance_pct)

    return {
        'quotation': quotation,
        'order':     order,
        'advance':   advance,
        'plan':      payment_plan(quotation, advance_pct),
    }


def _step_visuals_check(tenant_id: int, quotation: Quotation) -> None:
    """Fail early (before any state change) if the design is under revision."""
    from . import design_approval_service

    approval = design_approval_service.get_latest_for_project(
        tenant_id, quotation.project_id)
    if approval is None:
        return
    if approval.status not in (DesignApprovalStatus.APPROVED,
                               DesignApprovalStatus.APPROVAL_SENT,
                               DesignApprovalStatus.SUBMITTED):
        raise ValueError(
            'The design is being revised. Please wait for the updated design '
            'before approving.')


def payment_status(tenant_id: int, quotation: Quotation) -> dict | None:
    """Live payment ledger for an accepted quotation (customer-safe)."""
    from . import payment_service
    from ...models.payment import PaymentStatus

    order = quotation.active_order
    if not order:
        return None

    summary = payment_service.order_payment_summary(tenant_id, order.id)
    advance = payment_service.get_advance_for_order(tenant_id, order.id)
    return {
        'order_number':     order.order_number,
        'received':         summary['received'],
        'balance':          summary['balance'],
        'pct_received':     summary['pct_received'],
        'advance_due':      bool(advance and advance.status in PaymentStatus.OPEN),
        'advance_amount':   float(advance.invoice_amount) if advance else None,
        'advance_balance':  float(advance.balance) if advance else None,
        'advance_number':   advance.payment_number if advance else None,
    }
