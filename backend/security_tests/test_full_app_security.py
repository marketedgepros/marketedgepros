"""Exercise containment through the real full-app blueprint registration."""
from types import SimpleNamespace

import pytest


@pytest.fixture
def application(tmp_path):
    from src.app import create_app
    return create_app('testing', config_overrides={'UPLOAD_FOLDER': str(tmp_path)})


@pytest.mark.parametrize('endpoint,method,mail_method,code', [
    ('/api/v1/auth/resend-verification', 'resend_verification_code', 'send_verification_email', '123456'),
    ('/api/v1/auth/password/reset-request', 'request_password_reset', 'send_password_reset_email', '654321'),
])
def test_full_factory_email_codes_never_appear(application, monkeypatch, endpoint, method, mail_method, code):
    from src.routes.auth import AuthService, EmailService
    user = SimpleNamespace(id=123, email='fake@example.test')
    token = SimpleNamespace(user=user, code=code)
    monkeypatch.setattr(AuthService, method, lambda email: token)
    delivered = []
    monkeypatch.setattr(EmailService, mail_method, lambda recipient, value: delivered.append(value) or True)
    response = application.test_client().post(endpoint, json={'email': user.email})
    assert response.status_code == 200
    assert code not in response.get_data(as_text=True)
    assert delivered == [code]


def test_full_factory_kyc_is_private_and_profile_public(application, tmp_path):
    private = tmp_path / 'kyc' / '1' / 'proof.pdf'
    private.parent.mkdir(parents=True)
    private.write_bytes(b'private-document')
    public = tmp_path / 'profiles' / 'profile_1.png'
    public.parent.mkdir()
    public.write_bytes(b'public-avatar')
    client = application.test_client()
    denied = client.get('/api/v1/uploads/kyc/1/proof.pdf')
    assert denied.status_code == 404
    assert b'private-document' not in denied.data
    allowed = client.get('/api/v1/uploads/profiles/profile_1.png')
    assert allowed.status_code == 200
    assert allowed.data == b'public-avatar'
    allowed.close()
