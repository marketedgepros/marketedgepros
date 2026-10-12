"""KYC owner/reviewer tests with real JWT, User rows and filesystem documents."""
import io
from pathlib import Path

import pytest
from flask import Flask

from src.database import db
from src.models.user import User
from src.routes.kyc import kyc_bp
from src.services.auth_service import AuthService
from src.services.storage_service import storage_service
from src.utils.hierarchy_scoping import init_hierarchy_scoping


@pytest.fixture
def kyc_app(tmp_path, monkeypatch):
    from src.config import TestingConfig
    app = Flask(__name__)
    app.config.from_object(TestingConfig)
    app.config.update(UPLOAD_FOLDER=str(tmp_path / 'public'),
                      KYC_PRIVATE_UPLOAD_FOLDER=str(tmp_path / 'private'))
    db.init_app(app)
    app.register_blueprint(kyc_bp, url_prefix='/api/v1/kyc')
    from src.routes.admin import admin_bp
    from src.routes.uploads import uploads_bp
    app.register_blueprint(admin_bp, url_prefix='/api/v1/admin')
    app.register_blueprint(uploads_bp, url_prefix='/api/v1/uploads')
    init_hierarchy_scoping(db, User)
    monkeypatch.setattr(AuthService, 'is_token_blacklisted', lambda token: False)
    monkeypatch.setattr(storage_service, 'client', None)
    with app.app_context():
        User.__table__.create(db.engine)
        from src.models.token_blacklist import TokenBlacklist
        TokenBlacklist.__table__.create(db.engine)
        for identity, tenant, role, tree in [
            (1, 10, 'trader', '2/1'), (2, 10, 'master', '2'),
            (3, 10, 'trader', '3'), (4, 20, 'master', '4'),
            (5, None, 'master', '5'), (6, 10, 'master', '6'),
        ]:
            user = User(id=identity, email=f'fake{identity}@example.test', password_hash='fake-hash',
                        first_name='Fake', last_name='User', tenant_id=tenant, role=role,
                        tree_path=tree, is_active=True)
            db.session.add(user)
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def headers(app, identity):
    with app.app_context():
        user = db.session.get(User, identity)
        return {'Authorization': 'Bearer ' + user.generate_access_token()}


def upload(app, identity=1, kind='id_proof', content=b'%PDF-1.7\nsynthetic-data'):
    return app.test_client().post(f'/api/v1/kyc/documents/{kind}/upload',
        headers=headers(app, identity),
        data={'file': (io.BytesIO(content), 'proof.pdf')}, content_type='multipart/form-data')


def download_url(identity=1, kind='id_proof'):
    return f'/api/v1/kyc/documents/{identity}/{kind}/download'


def test_upload_persists_canonical_fields_and_private_owner_download(kyc_app):
    result = upload(kyc_app)
    assert result.status_code == 200
    with kyc_app.app_context():
        user = db.session.get(User, 1)
        assert user.kyc_id_status == 'pending'
        assert user.kyc_id_uploaded_at is not None
        assert user.kyc_id_url.startswith('local-kyc:kyc/1/id_proof_')
    response = kyc_app.test_client().get(download_url(), headers=headers(kyc_app, 1))
    assert response.status_code == 200
    assert response.data.startswith(b'%PDF-')
    assert 'attachment' in response.headers['Content-Disposition']
    assert 'no-store' in response.headers['Cache-Control']
    response.close()


@pytest.mark.parametrize('actor,status', [(None,401),(2,200),(3,404),(4,404),(5,404),(6,404)])
def test_download_owner_reviewer_and_tenant_policy(kyc_app, actor, status):
    assert upload(kyc_app).status_code == 200
    response = kyc_app.test_client().get(download_url(), headers=headers(kyc_app, actor) if actor else {})
    assert response.status_code == status
    if status != 200:
        assert b'synthetic-data' not in response.data
    response.close()


def test_admin_detail_returns_authenticated_url_not_storage_reference(kyc_app):
    assert upload(kyc_app).status_code == 200
    response = kyc_app.test_client().get('/api/v1/kyc/admin/submissions/1', headers=headers(kyc_app,2))
    assert response.status_code == 200
    documents = response.get_json()['documents']
    assert next(d for d in documents if d['type']=='id_proof')['url'] == download_url()
    assert 'local-kyc:' not in response.get_data(as_text=True)
    foreign = kyc_app.test_client().get('/api/v1/kyc/admin/submissions/1', headers=headers(kyc_app,4))
    assert foreign.status_code == 404


@pytest.mark.parametrize('reference', [
    'local-kyc:kyc/3/id_proof_20260101_123456.pdf',
    '/uploads/kyc/1/../../secret.pdf',
    'https://evil.example/kyc/1/id_proof_20260101_123456.pdf',
    'local-kyc:kyc/1/selfie_20260101_123456.pdf',
])
def test_untrusted_or_foreign_storage_metadata_is_not_used(kyc_app, reference):
    with kyc_app.app_context():
        db.session.get(User,1).kyc_id_url=reference
        db.session.commit()
    response=kyc_app.test_client().get(download_url(),headers=headers(kyc_app,1))
    assert response.status_code==404


def test_legacy_local_document_can_be_downloaded_only_after_auth(kyc_app):
    key='kyc/1/id_proof_20260101_123456.pdf'
    path=Path(kyc_app.config['UPLOAD_FOLDER'])/key
    path.parent.mkdir(parents=True)
    path.write_bytes(b'%PDF-1.7\nlegacy-fake')
    with kyc_app.app_context():
        db.session.get(User,1).kyc_id_url='/uploads/'+key
        db.session.commit()
    response=kyc_app.test_client().get(download_url(),headers=headers(kyc_app,1))
    assert response.status_code==200 and b'legacy-fake' in response.data
    response.close()


def test_private_symlink_is_not_followed(kyc_app,tmp_path):
    assert upload(kyc_app).status_code==200
    with kyc_app.app_context():
        key=db.session.get(User,1).kyc_id_url.removeprefix('local-kyc:')
    target=Path(kyc_app.config['KYC_PRIVATE_UPLOAD_FOLDER'])/key
    target.unlink()
    secret=tmp_path/'secret.pdf';secret.write_bytes(b'fake-secret')
    target.symlink_to(secret)
    response=kyc_app.test_client().get(download_url(),headers=headers(kyc_app,1))
    assert response.status_code==404 and b'fake-secret' not in response.data


def test_upload_rejects_format_mismatch_and_empty_content(kyc_app):
    assert upload(kyc_app,content=b'executable-not-pdf').status_code==400
    assert upload(kyc_app,content=b'').status_code==400
    with kyc_app.app_context():
        assert db.session.get(User,1).kyc_id_url is None


def test_spaces_failure_does_not_fall_back_to_local(kyc_app,monkeypatch):
    class FailedSpaces:
        def upload_fileobj(self,*args,**kwargs):
            raise RuntimeError('fake-provider-secret')
    monkeypatch.setattr(storage_service,'client',FailedSpaces())
    result=upload(kyc_app)
    assert result.status_code==500
    assert 'fake-provider-secret' not in result.get_data(as_text=True)
    assert not Path(kyc_app.config['KYC_PRIVATE_UPLOAD_FOLDER']).exists()
    with kyc_app.app_context():
        assert db.session.get(User,1).kyc_id_url is None


def test_legacy_upload_is_private_and_registered_to_user(kyc_app):
    result=kyc_app.test_client().post('/api/v1/uploads/kyc', headers=headers(kyc_app,1),
        data={'file': (io.BytesIO(b'%PDF-1.7\nlegacy-upload'), 'proof.pdf'), 'document_type':'id'},
        content_type='multipart/form-data')
    assert result.status_code==200
    with kyc_app.app_context():
        assert db.session.get(User,1).kyc_id_url.startswith('local-kyc:')
    response=kyc_app.test_client().get(download_url(),headers=headers(kyc_app,1))
    assert response.status_code==200 and b'legacy-upload' in response.data
    response.close()


def test_legacy_admin_kyc_links_do_not_expose_storage_references(kyc_app):
    assert upload(kyc_app).status_code==200
    with kyc_app.app_context():
        db.session.get(User,1).kyc_status='pending'
        db.session.commit()
    response=kyc_app.test_client().get('/api/v1/admin/kyc/pending',headers=headers(kyc_app,2))
    assert response.status_code==200
    payload=response.get_json()
    assert payload['owner_context']=={'user_id':2,'tenant_id':10}
    assert payload['review_scope']=='recorded_document_only'
    assert payload['submissions'][0]['user_id']==1
    assert 'kyc_id_url' not in response.get_data(as_text=True)
    assert 'local-kyc:' not in response.get_data(as_text=True)
    detail=kyc_app.test_client().get('/api/v1/kyc/admin/submissions/1',headers=headers(kyc_app,2))
    assert detail.status_code==200
    assert next(d for d in detail.get_json()['documents'] if d['type']=='id_proof')['url']==download_url()
    assert 'local-kyc:' not in detail.get_data(as_text=True)
    foreign=kyc_app.test_client().get('/api/v1/admin/kyc/pending',headers=headers(kyc_app,4))
    assert foreign.status_code==200 and foreign.get_json()['submissions']==[]
    assert kyc_app.test_client().get('/api/v1/kyc/admin/submissions/1',headers=headers(kyc_app,4)).status_code==404


def test_spaces_upload_acl_and_authenticated_download(kyc_app,monkeypatch):
    calls=[]
    class PrivateSpaces:
        def upload_fileobj(self,body,bucket,key,ExtraArgs):
            calls.append((bucket,key,ExtraArgs,body.read()))
        def get_object(self,Bucket,Key):
            assert Key==calls[0][1]
            return {'Body':io.BytesIO(calls[0][3]),'ContentLength':len(calls[0][3])}
    monkeypatch.setattr(storage_service,'client',PrivateSpaces())
    assert upload(kyc_app).status_code==200
    assert calls[0][2]['ACL']=='private'
    with kyc_app.app_context():
        assert db.session.get(User,1).kyc_id_url.startswith('spaces-kyc:')
    response=kyc_app.test_client().get(download_url(),headers=headers(kyc_app,1))
    assert response.status_code==200 and b'synthetic-data' in response.data
    response.close()


def test_private_local_storage_requires_explicit_configuration(kyc_app):
    kyc_app.config['KYC_ALLOW_PRIVATE_LOCAL_STORAGE']=False
    assert upload(kyc_app).status_code==500
    with kyc_app.app_context():
        assert db.session.get(User,1).kyc_id_url is None


def test_private_storage_cannot_be_inside_public_uploads(kyc_app):
    kyc_app.config['KYC_PRIVATE_UPLOAD_FOLDER']=str(Path(kyc_app.config['UPLOAD_FOLDER'])/'private')
    assert upload(kyc_app).status_code==500
    assert not Path(kyc_app.config['KYC_PRIVATE_UPLOAD_FOLDER']).exists()


@pytest.mark.parametrize('prefix',['/api/v1/kyc/admin/submissions','/api/v1/admin/kyc'])
@pytest.mark.parametrize('action',['approve','reject'])
def test_cross_tenant_review_cannot_change_document_or_user(kyc_app,prefix,action):
    assert upload(kyc_app).status_code==200
    with kyc_app.app_context():
        user=db.session.get(User,1)
        user.kyc_status='pending'
        db.session.commit()
    result=kyc_app.test_client().post(f'{prefix}/1/{action}',headers=headers(kyc_app,4),json={'reason':'foreign'})
    assert result.status_code==404
    with kyc_app.app_context():
        user=db.session.get(User,1)
        assert user.kyc_status=='pending' and user.kyc_id_status=='pending'


def test_private_root_symlink_ancestor_cannot_redirect_upload(kyc_app,tmp_path):
    public=Path(kyc_app.config['UPLOAD_FOLDER']);public.mkdir()
    alias=tmp_path/'alias';alias.symlink_to(public,target_is_directory=True)
    kyc_app.config['KYC_PRIVATE_UPLOAD_FOLDER']=str(alias/'private')
    assert upload(kyc_app).status_code in {400,500}
    assert not (public/'private').exists()


def test_permissive_preexisting_private_root_is_rejected(kyc_app):
    root=Path(kyc_app.config['KYC_PRIVATE_UPLOAD_FOLDER']);root.mkdir(mode=0o755)
    root.chmod(0o755)
    assert upload(kyc_app).status_code==400
    assert list(root.iterdir())==[]


def test_cookie_only_owner_download(kyc_app):
    assert upload(kyc_app).status_code==200
    client=kyc_app.test_client()
    token=headers(kyc_app,1)['Authorization'].removeprefix('Bearer ')
    client.set_cookie('access_token',token)
    response=client.get(download_url())
    assert response.status_code==200 and b'synthetic-data' in response.data
    response.close()


def test_root_supermaster_download_remains_tenant_bound(kyc_app):
    assert upload(kyc_app).status_code==200
    kyc_app.config['PLATFORM_ROOT_USER_ID']=6
    with kyc_app.app_context():
        root=db.session.get(User,6)
        root.role='supermaster'
        root.can_create_same_role=True
        root.is_verified=True
        db.session.commit()
    response=kyc_app.test_client().get(download_url(),headers=headers(kyc_app,6))
    assert response.status_code==200
    response.close()
    foreign=kyc_app.test_client().get(download_url(identity=4),headers=headers(kyc_app,6))
    assert foreign.status_code==404
