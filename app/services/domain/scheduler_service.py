import os
import sys
import threading
import time

_started = False
_lock = threading.Lock()


def run_payment_jobs(app) -> dict:
    """One pass: mark overdue milestones and raise any later-stage invoice that is due."""
    from ...extensions import db
    from . import payment_service

    with app.app_context():
        try:
            overdue  = payment_service.mark_overdue()
            invoiced = payment_service.auto_invoice_all()
            return {'overdue': overdue, 'invoiced': invoiced}
        except Exception:
            db.session.rollback()
            app.logger.exception('Payment scheduler pass failed')
            return {'overdue': 0, 'invoiced': 0}
        finally:
            db.session.remove()


def _loop(app, interval: int) -> None:
    time.sleep(min(interval, 60))
    while True:
        run_payment_jobs(app)
        time.sleep(interval)


def start_scheduler(app) -> None:
    """Start the payment background thread once per process."""
    global _started

    if app.config.get('TESTING'):
        return
    if os.environ.get('PAYMENT_SCHEDULER', '1') != '1':
        return
    if os.path.basename(sys.argv[0]).lower() in ('flask', 'flask.exe', 'alembic'):
        return
    if app.debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return

    with _lock:
        if _started:
            return
        _started = True

    interval = int(app.config.get('PAYMENT_SCHEDULER_INTERVAL', 900))
    threading.Thread(
        target=_loop, args=(app, interval), name='payment-scheduler', daemon=True
    ).start()
