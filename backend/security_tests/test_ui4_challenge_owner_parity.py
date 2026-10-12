"""Real isolated Flask challenge responses for frontend parity, synthetic only."""
import json

from test_challenge_list_contract import application, challenge_data, sqlite_jsonb_compiler


def test_ui4_challenge_owner_context_is_server_derived(application, challenge_data, record_property):
    from src.database import db
    from src.models.mt5_models import MT5Account
    from src.models.user import User

    with application.app_context():
        db.metadata.create_all(bind=db.engine, tables=[MT5Account.__table__])
        actor = db.session.get(User, challenge_data['ids']['owner'])
        expected = {'user_id': actor.id, 'tenant_id': actor.tenant_id}
    try:
        client = application.test_client()
        headers = challenge_data['headers']['owner']
        listing = client.get('/api/v1/challenges/my-challenges?status=active', headers=headers)
        assert listing.status_code == 200
        payload = listing.get_json()
        assert payload['owner_context'] == expected
        assert all(row['user_id'] == expected['user_id'] for row in payload['challenges'])
        detail = client.get(f"/api/v1/challenges/{challenge_data['ids']['owner_zero_null']}/progress", headers=headers)
        assert detail.status_code == 200
        progress = detail.get_json()
        assert progress['owner_context'] == expected
        assert progress['challenge']['user_id'] == expected['user_id']
        assert progress['provider_authenticated'] is False
        assert progress['challenge']['current_balance'] == '0.00'
        assert progress['challenge']['initial_balance'] is None
        assert client.get(f"/api/v1/challenges/{challenge_data['ids']['peer_challenge']}/progress", headers=headers).status_code == 404
        assert client.get(f"/api/v1/challenges/{challenge_data['ids']['owner_foreign_program']}/progress", headers=headers).status_code == 404
        for name, body in [('ui4_challenge_list_response', payload), ('ui4_challenge_progress_response', progress)]:
            record_property(name, json.dumps(body, sort_keys=True))
    finally:
        with application.app_context():
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=[MT5Account.__table__])
