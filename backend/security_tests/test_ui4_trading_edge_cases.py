"""Additional bounded input/window/service regressions; isolated synthetic data."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event
from test_ui4_trading_scaling import ui4_app, _headers


def test_ui4_history_period_windows_do_not_include_future_records(ui4_app):
    from src.database import db
    from src.models.trade import Trade
    with ui4_app.app_context():
        db.session.add(Trade(id=1999, ticket='UI4-FUTURE', challenge_id=100, symbol='FUTURE',
                             trade_type='buy', volume=Decimal('1.00'), open_price=Decimal('1.00000'),
                             profit=Decimal('9.00'), status='closed', open_time=datetime.utcnow(),
                             close_time=datetime.utcnow() + timedelta(days=1)))
        db.session.commit()
    client = ui4_app.test_client()
    for period in ('today', 'week', 'month'):
        result = client.get(f'/api/v1/traders/history?symbol=FUTURE&period={period}', headers=_headers(ui4_app))
        assert result.status_code == 200
        assert result.get_json()['trades'] == []
        assert result.get_json()['pagination']['total'] == 0
    assert client.get('/api/v1/traders/history?symbol=FUTURE&period=all', headers=_headers(ui4_app)).get_json()['pagination']['total'] == 1


@pytest.mark.parametrize('query', ['page=01', 'per_page=020', 'page=' + '9' * 1000, 'per_page=101', 'period=this_month', 'symbol=%25', 'symbol=EURUSD&symbol=GBPUSD'])
def test_ui4_history_invalid_inputs_are_rejected_before_resource_sql(ui4_app, query):
    from src.database import db
    statements = []
    with ui4_app.app_context():
        engine = db.engine
    def observe(_conn, _cursor, statement, *_args):
        statements.append(statement.lower())
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        response = ui4_app.test_client().get('/api/v1/traders/history?' + query, headers=_headers(ui4_app))
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert response.status_code == 400
    assert response.get_json()['code'] == 'TRADING_HISTORY_QUERY_INVALID'
    assert not any('trades' in sql or 'challenges' in sql for sql in statements)


@pytest.mark.parametrize('query', ['page=01', 'per_page=020', 'page=' + '9' * 1000, 'per_page=101', 'page=1&page=2', 'symbol=EURUSD'])
def test_ui4_scaling_invalid_pagination_is_rejected_before_resource_sql(ui4_app, query):
    from src.database import db
    statements = []
    with ui4_app.app_context():
        engine = db.engine
    def observe(_conn, _cursor, statement, *_args):
        statements.append(statement.lower())
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        response = ui4_app.test_client().get('/api/v1/scaling/admin/all-users?' + query, headers=_headers(ui4_app, 2))
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert response.status_code == 400
    assert not any('account_scaling' in sql for sql in statements)


def test_ui4_scaling_service_mutations_do_not_query_or_write(ui4_app):
    from src.database import db
    from src.services.scaling_service import ScalingService
    statements = []
    with ui4_app.app_context():
        engine = db.engine
        def observe(_conn, _cursor, statement, *_args):
            statements.append(statement)
        event.listen(engine, 'before_cursor_execute', observe)
        try:
            for name in ('initialize_scaling_for_user', 'update_profit', 'perform_scale_up', 'pause_scaling', 'resume_scaling'):
                result = getattr(ScalingService, name)(object(), Decimal('999.00'))
                assert result == {'success': False, 'error': 'Scaling evidence is not configured', 'code': 'SCALING_EVIDENCE_NOT_CONFIGURED'}
        finally:
            event.remove(engine, 'before_cursor_execute', observe)
    assert statements == []
