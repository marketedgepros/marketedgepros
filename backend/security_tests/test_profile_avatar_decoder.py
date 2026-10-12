"""Profile upload content/MIME/key regressions. No storage network is used."""
import io

import pytest
from werkzeug.datastructures import FileStorage

from src.services.profile_contract import ProfileContractError, avatar_storage_key, validate_avatar_file
from test_profile_account_contract import PNG_1X1, profile_app, _headers


@pytest.mark.parametrize('name,body', [
    ('fake.png', b'\x89PNG\r\n\x1a\n' + b'fake-image-header'),
    ('fake.gif', b'GIF89a\x01\x00\x01\x00\x00\x00\x00,;'),
    ('fake.webp', b'RIFF' + (12).to_bytes(4, 'little') + b'WEBPVP8 ' + (0).to_bytes(4, 'little')),
    ('fake.jpg', b'\xff\xd8\xff\xc0\x00\x08\x08\x00\x01\x00\x01\x03\xff\xda\x00\x02junk\xff\xd9'),
])
def test_profile_decoder_rejects_signature_only_images(name, body):
    file = FileStorage(stream=io.BytesIO(body), filename=name, content_type='image/png')
    with pytest.raises(ProfileContractError):
        validate_avatar_file(file)
    assert file.stream.tell() == 0


def test_profile_server_replaces_client_html_mime_with_decoded_image_mime(profile_app, monkeypatch):
    seen = []
    def upload(file, user_id):
        seen.append((file.content_type, file.read(), user_id))
        return {'success': True, 'url': '/uploads/profiles/1/avatar.png', 'key': 'profiles/1/avatar.png'}
    monkeypatch.setattr('src.routes.profile.storage_service.upload_profile_image', upload)
    response = profile_app.test_client().post('/api/v1/profile/avatar', headers=_headers(profile_app),
        data={'avatar': (io.BytesIO(PNG_1X1), 'avatar.png', 'text/html')}, content_type='multipart/form-data')
    assert response.status_code == 200
    assert seen == [('image/png', PNG_1X1, 1)]
    assert response.get_json()['user']['id'] == 1


@pytest.mark.parametrize('url', [
    '/uploads/profiles/1/avatar.png/../../../foreign.png',
    '/uploads/profiles/1/avatar.png?key=other',
    '/uploads/profiles/1/avatar.png#secret',
    '/uploads/profiles/1/avatar.%70ng',
    '/uploads/profiles/2/avatar.png',
    'https://name:secret@bucket.ams3.digitaloceanspaces.com/profiles/1/avatar.png',
    'https://notdigitaloceanspaces.com/profiles/1/avatar.png',
    'https://evil.example/profiles/1/avatar.png',
])
def test_profile_avatar_delete_uses_only_literal_owner_key(url):
    assert avatar_storage_key(url, 1) is None


@pytest.mark.parametrize('result', [
    {'success': True, 'url': '/uploads/profiles/2/avatar.png', 'key': 'profiles/1/avatar.png'},
    {'success': True, 'url': '/uploads/profiles/1/avatar.png', 'key': 'profiles/2/avatar.png'},
    {'success': True, 'url': 'https://other.ams3.cdn.digitaloceanspaces.com/profiles/1/avatar.png', 'key': 'profiles/1/avatar.png'},
    {'success': True, 'url': '/uploads/profiles/1/avatar.jpg', 'key': 'profiles/1/avatar.png'},
    {'success': True, 'url': '/uploads/profiles/1/avatar.png'},
])
def test_profile_rejects_storage_success_with_unbound_url_or_key(profile_app, monkeypatch, result):
    calls = []
    monkeypatch.setattr('src.routes.profile.storage_service.upload_profile_image', lambda *args: result)
    monkeypatch.setattr('src.routes.profile.storage_service.delete_file', lambda key: calls.append(key) or True)
    response = profile_app.test_client().post('/api/v1/profile/avatar', headers=_headers(profile_app),
        data={'avatar': (io.BytesIO(PNG_1X1), 'avatar.png', 'image/png')}, content_type='multipart/form-data')
    assert response.status_code == 503
    assert response.get_json() == {'error': 'Avatar upload failed'}
    assert profile_app.test_client().get('/api/v1/profile', headers=_headers(profile_app)).get_json()['user']['avatar_url'] is None
    assert not calls


def test_profile_canonical_configured_cdn_success(profile_app, monkeypatch):
    from src.services.storage_service import storage_service
    url = storage_service.cdn_endpoint + '/profiles/1/avatar.png'
    monkeypatch.setattr(storage_service, 'upload_profile_image', lambda *args: {'success': True, 'url': url, 'key': 'profiles/1/avatar.png'})
    response = profile_app.test_client().post('/api/v1/profile/avatar', headers=_headers(profile_app),
        data={'avatar': (io.BytesIO(PNG_1X1), 'avatar.png', 'image/png')}, content_type='multipart/form-data')
    assert response.status_code == 200
    assert response.get_json()['avatar_url'] == url
