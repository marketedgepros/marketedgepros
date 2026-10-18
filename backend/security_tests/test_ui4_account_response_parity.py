"""Actual isolated Flask/KYC responses for frontend contract parity; synthetic only."""
import json

from test_kyc_private_download import kyc_app, headers, upload


def test_ui4_kyc_response_contract_before_and_after_upload(kyc_app, record_property):
    client = kyc_app.test_client()
    before = client.get('/api/v1/kyc/documents', headers=headers(kyc_app, 1))
    assert before.status_code == 200
    initial = before.get_json()
    assert initial['overall_status'] == 'not_submitted'
    assert len(initial['documents']) == 4
    assert all(doc['status'] == 'not_uploaded' and doc['url'] is None
               for doc in initial['documents'])
    submitted = upload(kyc_app)
    assert submitted.status_code == 200
    body = submitted.get_json()
    assert body['document']['type'] == 'id_proof'
    assert body['document']['status'] == 'pending'
    after = client.get('/api/v1/kyc/documents', headers=headers(kyc_app, 1))
    assert after.status_code == 200
    final = after.get_json()
    proof = next(doc for doc in final['documents'] if doc['type'] == 'id_proof')
    assert proof['status'] == 'pending'
    assert proof['url'] == '/api/v1/kyc/documents/1/id_proof/download'
    assert final['statistics']['pending'] == 1
    assert final['overall_status'] == 'not_submitted'
    assert 'local-kyc:' not in json.dumps(final)
    for name, response in [('kyc_before_response', initial), ('kyc_upload_response', body),
                           ('kyc_after_response', final)]:
        record_property(name, json.dumps(response, sort_keys=True))
