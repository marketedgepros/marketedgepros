"""Real quote HTTP responses carry row-authoritative owner/brand on POST/replay/GET."""
from test_order_quotes import quote_app, _create, _headers


def test_program_catalog_quote_http_owner_brand_post_replay_get(quote_app):
    first = _create(quote_app)
    replay = _create(quote_app)
    assert first.status_code == 201 and replay.status_code == 200
    first_order = first.get_json()['order']
    replay_order = replay.get_json()['order']
    read = quote_app.test_client().get('/api/v1/orders/' + first_order['id'], headers=_headers(quote_app))
    assert read.status_code == 200
    for order in (first_order, replay_order, read.get_json()['order']):
        assert order['user_id'] == order['snapshot']['user_id'] == 2
        assert order['tenant_id'] == order['snapshot']['tenant_id'] == 1
        assert order['id'] == first_order['id']
        assert order['paid'] is False and order['snapshot']['entitlement'] is False
    assert replay.get_json()['replayed'] is True
    denied = quote_app.test_client().get('/api/v1/orders/' + first_order['id'], headers=_headers(quote_app, actor=3))
    assert denied.status_code == 404
