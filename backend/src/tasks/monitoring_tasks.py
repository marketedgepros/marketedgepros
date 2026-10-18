"""MT5 monitoring tasks remain unconfigured until source/rules/commands exist.

Task names are retained for compatibility with existing Celery configuration.
No schedules are created here. Invoking any legacy task returns unavailable
before DB reads/writes, account disablement, task enqueue or notifications.
Stored balances and mutable rules alone cannot attest a trading violation or
provider-confirmed suspension. Future bounded event processing replaces this
legacy polling/synchronous side-effect chain.
"""
from celery import shared_task


def _unavailable():
    return {'success': False, 'code': 'MT5_PROVIDER_NOT_CONFIGURED',
            'error': 'Verified MT5 source and versioned monitoring rules are not configured',
            'provider_confirmed': False}


@shared_task(name='monitoring.sync_mt5_trades')
def sync_mt5_trades():
    return _unavailable()


@shared_task(name='monitoring.sync_challenge_data')
def sync_challenge_data(challenge_id):
    return _unavailable()


@shared_task(name='monitoring.check_all_violations')
def check_all_violations():
    return _unavailable()


@shared_task(name='monitoring.check_challenge_violations')
def check_challenge_violations(challenge_id):
    return _unavailable()


@shared_task(name='monitoring.disable_mt5_account')
def disable_mt5_account_task(challenge_id, violations):
    return _unavailable()


@shared_task(name='monitoring.send_violation_notifications')
def send_violation_notifications(challenge_id, violations):
    return _unavailable()


@shared_task(name='monitoring.sync_challenge_immediate')
def sync_challenge_immediate(challenge_id):
    return _unavailable()


def log_monitoring_event(challenge_id, event_type, event_data):
    return _unavailable()


def log_violation(challenge_id, violation_type, violation_data, action_taken):
    return _unavailable()
