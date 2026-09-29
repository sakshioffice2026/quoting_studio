import calendar as pycal
from collections import defaultdict
from datetime import date

from flask import Blueprint, render_template, request, url_for
from flask_login import login_required, current_user

from ..models import Survey, Delivery, Installation, ServiceTicket, Order, Quotation
from ..models.order import OrderStatus
from ..models.quotation import QuotationStatus

calendar_bp = Blueprint('calendar', __name__)


def _parse_month(raw: str | None) -> tuple[int, int]:
    today = date.today()
    if raw:
        try:
            y, m = raw.split('-')
            y, m = int(y), int(m)
            if 1 <= m <= 12 and 1970 <= y <= 2200:
                return y, m
        except (ValueError, TypeError):
            pass
    return today.year, today.month


def _shift(y: int, m: int, delta: int) -> str:
    idx = (y * 12 + (m - 1)) + delta
    return f'{idx // 12:04d}-{idx % 12 + 1:02d}'


def _collect(tenant_id: int, start: date, end: date) -> list[dict]:
    events: list[dict] = []

    def add(day, kind, label, url, tone):
        if day:
            events.append({'date': day, 'kind': kind, 'label': label, 'url': url, 'tone': tone})

    for s in (Survey.query
              .filter(Survey.tenant_id == tenant_id,
                      Survey.scheduled_date.isnot(None),
                      Survey.scheduled_date.between(start, end))
              .all()):
        who = s.lead.display_name if s.lead else f'#{s.id}'
        add(s.scheduled_date, 'Survey', f'Survey · {who}',
            url_for('survey.detail', survey_id=s.id), 'survey')

    for d in (Delivery.query
              .filter(Delivery.tenant_id == tenant_id,
                      Delivery.scheduled_dispatch_date.isnot(None),
                      Delivery.scheduled_dispatch_date.between(start, end))
              .all()):
        add(d.scheduled_dispatch_date, 'Delivery', f'Dispatch · {d.delivery_number}',
            url_for('delivery.detail', delivery_id=d.id), 'delivery')

    for i in (Installation.query
              .filter(Installation.tenant_id == tenant_id,
                      Installation.scheduled_date.isnot(None),
                      Installation.scheduled_date.between(start, end))
              .all()):
        add(i.scheduled_date, 'Installation', f'Install · {i.install_number}',
            url_for('installation.detail', installation_id=i.id), 'install')

    for t in (ServiceTicket.query
              .filter(ServiceTicket.tenant_id == tenant_id,
                      ServiceTicket.scheduled_date.isnot(None),
                      ServiceTicket.scheduled_date.between(start, end))
              .all()):
        add(t.scheduled_date, 'Service', f'Service · {t.ticket_number}',
            url_for('amc.ticket_detail', ticket_id=t.id), 'service')

    for o in (Order.query
              .filter(Order.tenant_id == tenant_id,
                      Order.status != OrderStatus.CANCELLED,
                      Order.promised_delivery_date.isnot(None),
                      Order.promised_delivery_date.between(start, end))
              .all()):
        add(o.promised_delivery_date, 'Promised', f'Promised · {o.order_number}',
            url_for('order.detail', order_id=o.id), 'order')

    for q in (Quotation.query
              .filter(Quotation.tenant_id == tenant_id,
                      Quotation.status.in_([QuotationStatus.SENT, QuotationStatus.NEGOTIATION]),
                      Quotation.validity_date.isnot(None),
                      Quotation.validity_date.between(start, end))
              .all()):
        add(q.validity_date, 'Quote', f'Quote expires · {q.quotation_number}',
            url_for('quotation.detail', quotation_id=q.id), 'quote')

    return events


@calendar_bp.route('/calendar')
@login_required
def index():
    year, month = _parse_month(request.args.get('month'))
    weeks = pycal.Calendar(firstweekday=0).monthdatescalendar(year, month)
    start, end = weeks[0][0], weeks[-1][-1]

    events = _collect(current_user.tenant_id, start, end)
    by_day: dict[date, list[dict]] = defaultdict(list)
    for e in events:
        by_day[e['date']].append(e)

    in_month = sorted(
        (e for e in events if e['date'].year == year and e['date'].month == month),
        key=lambda e: (e['date'], e['kind']),
    )

    return render_template(
        'calendar.html',
        weeks=weeks,
        by_day=by_day,
        agenda=in_month,
        year=year,
        month=month,
        month_label=date(year, month, 1).strftime('%B %Y'),
        prev_month=_shift(year, month, -1),
        next_month=_shift(year, month, 1),
        today=date.today(),
    )
