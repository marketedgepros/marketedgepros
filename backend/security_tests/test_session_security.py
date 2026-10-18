"""Real JWT/DB/HTTP checks for session, refresh, CSRF and two-factor boundaries."""
from datetime import timedelta
import jwt
import pyotp
import pytest
from flask import Flask, jsonify

from src.config import TestingConfig
from src.database import db
from src.models.user import User
from src.models.token_blacklist import TokenBlacklist
from src.routes.auth import auth_bp
from src.services.session_service import SessionService
from src.services.two_factor_service import TwoFactorService
from src.utils.decorators import token_required
from src.middleware.auth import jwt_required


@pytest.fixture
def session_app():
    app=Flask(__name__)
    app.config.from_object(TestingConfig)
    db.init_app(app)
    app.register_blueprint(auth_bp,url_prefix='/api/v1/auth')
    @app.route('/protected',methods=['GET','POST'])
    @token_required
    def protected(user):
        return jsonify({'id':user.id})
    @app.route('/legacy-protected',methods=['GET','POST'])
    @jwt_required
    def legacy_protected():
        return jsonify({'ok':True})
    with app.app_context():
        db.metadata.create_all(db.engine,tables=[User.__table__,TokenBlacklist.__table__])
        user=User(id=1,email='synthetic@example.test',first_name='Fake',last_name='User',
                  password_hash='unused',is_verified=True,is_active=True,tenant_id=1,tree_path='1')
        user.set_password('InitialStrong42!')
        db.session.add(user);db.session.commit()
    yield app
    with app.app_context():
        db.session.remove();db.engine.dispose()


def tokens(app):
    with app.app_context():
        user=db.session.get(User,1)
        return SessionService.issue(user)


@pytest.mark.parametrize('path',['/protected','/legacy-protected'])
def test_token_type_and_version_are_enforced_on_both_decorators(session_app,path):
    access,refresh=tokens(session_app)
    client=session_app.test_client()
    assert client.get(path,headers={'Authorization':'Bearer '+access}).status_code==200
    assert client.get(path,headers={'Authorization':'Bearer '+refresh}).status_code==401
    with session_app.app_context():
        db.session.get(User,1).token_version=1;db.session.commit()
    assert client.get(path,headers={'Authorization':'Bearer '+access}).status_code==401
    assert client.get(path,headers={'Authorization':'Basic '+access}).status_code==401


def test_refresh_rotates_once_and_rejects_legacy_and_inactive(session_app):
    access,refresh=tokens(session_app)
    client=session_app.test_client()
    first=client.post('/api/v1/auth/refresh',json={'refresh_token':refresh})
    assert first.status_code==200
    data=first.get_json();assert data['refresh_token']!=refresh and data['csrf_token']
    assert 'HttpOnly' in ''.join(first.headers.getlist('Set-Cookie'))
    fresh_client=session_app.test_client()
    assert fresh_client.post('/api/v1/auth/refresh',json={'refresh_token':refresh}).status_code==401
    with session_app.app_context():
        old=jwt.decode(refresh,session_app.config['JWT_SECRET_KEY'],algorithms=['HS256'])
        old.pop('jti');old.pop('token_version');legacy=jwt.encode(old,session_app.config['JWT_SECRET_KEY'],algorithm='HS256')
        db.session.get(User,1).is_active=False;db.session.commit()
    assert fresh_client.post('/api/v1/auth/refresh',json={'refresh_token':legacy}).status_code==401
    assert fresh_client.post('/api/v1/auth/refresh',json={'refresh_token':data['refresh_token']}).status_code==401


def test_logout_revokes_access_and_unpresented_refresh(session_app):
    access,refresh=tokens(session_app)
    client=session_app.test_client()
    assert client.post('/api/v1/auth/logout',headers={'Authorization':'Bearer '+access}).status_code==200
    new_client=session_app.test_client()
    assert new_client.get('/protected',headers={'Authorization':'Bearer '+access}).status_code==401
    assert new_client.post('/api/v1/auth/refresh',json={'refresh_token':refresh}).status_code==401
    with session_app.app_context():assert db.session.get(User,1).token_version==0


def test_revocation_db_failure_fails_closed_and_logout_never_claims_success(session_app):
    access,_=tokens(session_app)
    with session_app.app_context():TokenBlacklist.__table__.drop(db.engine)
    client=session_app.test_client()
    assert client.get('/protected',headers={'Authorization':'Bearer '+access}).status_code==503
    assert client.post('/api/v1/auth/logout',headers={'Authorization':'Bearer '+access}).status_code==503


def test_password_bound_second_factor_and_challenge_reuse(session_app):
    with session_app.app_context():
        user=db.session.get(User,1);user.two_factor_enabled=True
        user.two_factor_secret=pyotp.random_base32();db.session.commit()
        code=pyotp.TOTP(user.two_factor_secret).now()
    client=session_app.test_client()
    bypass=client.post('/api/v1/auth/login/2fa',json={'user_id':1,'token':code})
    assert bypass.status_code==400
    login=client.post('/api/v1/auth/login',json={'email':'synthetic@example.test','password':'InitialStrong42!'})
    assert login.status_code==200
    challenge=login.get_json()['challenge_token']
    assert 'access_token' not in login.get_json()
    completed=client.post('/api/v1/auth/login/2fa',json={'challenge_token':challenge,'user_id':1,'token':code})
    assert completed.status_code==200 and completed.get_json()['access_token']
    assert session_app.test_client().post('/api/v1/auth/login/2fa',json={'challenge_token':challenge,'token':code}).status_code==401


@pytest.mark.parametrize('path',['/protected','/legacy-protected'])
def test_cookie_mutations_require_session_bound_csrf(session_app,path):
    from src.middleware.csrf_middleware import generate_csrf_token
    access,refresh=tokens(session_app)
    with session_app.app_context():csrf=generate_csrf_token(access,refresh)
    client=session_app.test_client();client.set_cookie('access_token',access)
    assert client.get(path).status_code==200
    assert client.post(path).status_code==403
    client.set_cookie('csrf_token','forged')
    assert client.post(path,headers={'X-CSRF-Token':'forged'}).status_code==403
    client.set_cookie('csrf_token',csrf)
    assert client.post(path,headers={'X-CSRF-Token':csrf}).status_code==200
    other_access,_=tokens(session_app)
    client.set_cookie('access_token',other_access)
    assert client.post(path,headers={'X-CSRF-Token':csrf}).status_code==403


def test_cookie_refresh_requires_bound_csrf_and_rotates_it(session_app):
    from src.middleware.csrf_middleware import generate_csrf_token
    access,refresh=tokens(session_app)
    with session_app.app_context():csrf=generate_csrf_token(access,refresh)
    client=session_app.test_client();client.set_cookie('refresh_token',refresh);client.set_cookie('csrf_token',csrf)
    assert client.post('/api/v1/auth/refresh').status_code==403
    response=client.post('/api/v1/auth/refresh',headers={'X-CSRF-Token':csrf})
    assert response.status_code==200 and response.get_json()['csrf_token']!=csrf


def test_2fa_challenge_wrong_subject_inactive_and_expired_are_rejected(session_app):
    import datetime
    with session_app.app_context():
        user=db.session.get(User,1);user.two_factor_enabled=True;user.two_factor_secret=pyotp.random_base32();db.session.commit()
        code=pyotp.TOTP(user.two_factor_secret).now();challenge=TwoFactorService.issue(user)
        claims=jwt.decode(challenge,session_app.config['JWT_SECRET_KEY'],algorithms=['HS256']);claims['exp']=1
        expired=jwt.encode(claims,session_app.config['JWT_SECRET_KEY'],algorithm='HS256')
    client=session_app.test_client()
    assert client.post('/api/v1/auth/login/2fa',json={'challenge_token':challenge,'user_id':2,'token':code}).status_code==401
    assert client.post('/api/v1/auth/login/2fa',json={'challenge_token':expired,'token':code}).status_code==401
    with session_app.app_context():db.session.get(User,1).is_active=False;db.session.commit()
    assert client.post('/api/v1/auth/login/2fa',json={'challenge_token':challenge,'token':code}).status_code==401


def test_logout_is_scoped_to_family_after_refresh_and_keeps_other_device(session_app):
    a_access,a_refresh=tokens(session_app)
    b_access,b_refresh=tokens(session_app)
    first=session_app.test_client().post('/api/v1/auth/refresh',json={'refresh_token':a_refresh})
    assert first.status_code==200
    rotated=first.get_json()
    assert session_app.test_client().post('/api/v1/auth/logout',headers={'Authorization':'Bearer '+a_access}).status_code==200
    independent=session_app.test_client()
    assert independent.get('/protected',headers={'Authorization':'Bearer '+rotated['access_token']}).status_code==401
    assert independent.post('/api/v1/auth/refresh',json={'refresh_token':rotated['refresh_token']}).status_code==401
    assert independent.get('/protected',headers={'Authorization':'Bearer '+b_access}).status_code==200
    assert independent.post('/api/v1/auth/refresh',json={'refresh_token':b_refresh}).status_code==200


@pytest.mark.parametrize('claim',['exp','iat','user_id','type'])
def test_required_claims_missing_are_denied(session_app,claim):
    access,_=tokens(session_app)
    claims=jwt.decode(access,session_app.config['JWT_SECRET_KEY'],algorithms=['HS256']);claims.pop(claim)
    malformed=jwt.encode(claims,session_app.config['JWT_SECRET_KEY'],algorithm='HS256')
    assert session_app.test_client().get('/protected',headers={'Authorization':'Bearer '+malformed}).status_code==401


def test_full_factory_login_cookie_csrf_password_change_revokes_sessions():
    from src.app import create_app
    from src.models.user import PasswordResetToken
    app=create_app('testing',config_overrides={'SQLALCHEMY_DATABASE_URI':'sqlite:///:memory:'})
    with app.app_context():
        db.metadata.create_all(db.engine,tables=[User.__table__,TokenBlacklist.__table__,PasswordResetToken.__table__])
        user=User(id=1,email='factory@example.test',first_name='Test',last_name='User',is_active=True,is_verified=True,tenant_id=1)
        user.set_password('InitialStrong42!');db.session.add(user);db.session.commit()
        delivery=PasswordResetToken(1);db.session.add(delivery);db.session.commit()
    try:
        client=app.test_client()
        login=client.post('/api/v1/auth/login',json={'email':'factory@example.test','password':'InitialStrong42!'})
        assert login.status_code==200
        data=login.get_json()
        assert client.get('/api/v1/auth/me').status_code==200
        assert client.put('/api/v1/profile/password',json={'current_password':'InitialStrong42!','new_password':'NextStrong43!'}).status_code==403
        changed=client.put('/api/v1/profile/password',json={'current_password':'InitialStrong42!','new_password':'NextStrong43!'},headers={'X-CSRF-Token':data['csrf_token']})
        assert changed.status_code==200
        with app.app_context():assert PasswordResetToken.query.filter_by(user_id=1).one().used is True
        assert client.get('/api/v1/auth/me').status_code==401
        assert app.test_client().post('/api/v1/auth/refresh',json={'refresh_token':data['refresh_token']}).status_code==401
    finally:
        with app.app_context():db.session.remove();db.engine.dispose()


def test_auth_http_reset_and_email_codes_consumed_once_with_redacted_audit(session_app,monkeypatch):
    from src.models.user import PasswordResetToken,EmailVerificationToken
    from src.models.verification_attempt import VerificationAttempt
    from src.services.email_service import EmailService
    from src.services.auth_token_service import AuthTokenService
    monkeypatch.setattr(EmailService,'send_welcome_email',staticmethod(lambda user:True))
    with session_app.app_context():
        db.metadata.create_all(db.engine,tables=[PasswordResetToken.__table__,EmailVerificationToken.__table__,VerificationAttempt.__table__])
        user=db.session.get(User,1);user.is_verified=False;db.session.commit()
        verification=AuthTokenService.resend_verification_code(user.email);code=verification.code
    client=session_app.test_client()
    assert client.post('/api/v1/auth/verify-email',json={'email':'synthetic@example.test','code':code}).status_code==200
    assert client.post('/api/v1/auth/verify-email',json={'email':'synthetic@example.test','code':code}).status_code==400
    with session_app.app_context():
        assert {x.code_entered for x in VerificationAttempt.query.all()}=={'******'}
        reset=AuthTokenService.request_password_reset('synthetic@example.test');reset_code=reset.code
        access,refresh=SessionService.issue(db.session.get(User,1))
    verified=client.post('/api/v1/auth/password/verify-code',json={'email':'synthetic@example.test','code':reset_code})
    assert verified.status_code==200 and verified.get_json()=={'message':'Reset code verified successfully','valid':True}
    reset=client.post('/api/v1/auth/password/reset-with-code',json={'email':'synthetic@example.test','code':reset_code,'new_password':'NewStrong42!'})
    assert reset.status_code==200
    assert client.post('/api/v1/auth/password/reset-with-code',json={'email':'synthetic@example.test','code':reset_code,'new_password':'OtherStrong42!'}).status_code==400
    assert client.get('/protected',headers={'Authorization':'Bearer '+access}).status_code==401
    assert client.post('/api/v1/auth/refresh',json={'refresh_token':refresh}).status_code==401


def test_profile_email_change_invalidates_old_delivery_tokens_and_sessions(session_app,monkeypatch):
    from src.routes.profile import profile_bp
    from src.models.user import PasswordResetToken,EmailVerificationToken
    from src.services.auth_token_service import AuthTokenService
    session_app.register_blueprint(profile_bp,url_prefix='/api/v1/profile')
    from email_validator import validate_email
    monkeypatch.setattr('src.routes.profile.validate_email_format',lambda value:(True,validate_email(value,check_deliverability=False).normalized))
    with session_app.app_context():
        db.metadata.create_all(db.engine,tables=[EmailVerificationToken.__table__,PasswordResetToken.__table__])
        verification=EmailVerificationToken(1);reset=PasswordResetToken(1)
        db.session.add_all([verification,reset]);db.session.commit()
        verify_value=verification.token;reset_value=reset.token
    access,refresh=tokens(session_app)
    client=session_app.test_client()
    result=client.put('/api/v1/profile',headers={'Authorization':'Bearer '+access},json={'email':'synthetic-new@example.com'})
    assert result.status_code==200
    with session_app.app_context():
        assert db.session.get(User,1).is_verified is False
        with pytest.raises(ValueError):AuthTokenService.verify_email(verify_value)
        db.session.rollback()
        with pytest.raises(ValueError):AuthTokenService.reset_password(reset_value,'StrongReset42!')
        db.session.rollback()
    assert client.get('/protected',headers={'Authorization':'Bearer '+access}).status_code==401
    assert client.post('/api/v1/auth/refresh',json={'refresh_token':refresh}).status_code==401


def test_admin_reset_revokes_target_but_not_admin_and_denies_foreign_tenant(session_app):
    from src.routes.admin import admin_bp
    from src.models.user import PasswordResetToken
    session_app.register_blueprint(admin_bp,url_prefix='/api/v1/admin')
    with session_app.app_context():
        PasswordResetToken.__table__.create(db.engine)
        user=db.session.get(User,1);user.role='supermaster';db.session.commit()
        peer=User(id=2,email='peer@example.test',first_name='Peer',last_name='Test',password_hash='unused',is_active=True,is_verified=True,tenant_id=1,tree_path='1/2')
        foreign=User(id=3,email='foreign@example.test',first_name='Foreign',last_name='Test',password_hash='unused',is_active=True,is_verified=True,tenant_id=2,tree_path='3')
        peer.set_password('OldStrong42!');foreign.set_password('OldStrong42!');db.session.add_all([peer,foreign]);db.session.commit()
        peer_access,peer_refresh=SessionService.issue(peer)
        delivery=PasswordResetToken(2);db.session.add(delivery);db.session.commit()
    admin_access,_=tokens(session_app)
    headers={'Authorization':'Bearer '+admin_access}
    client=session_app.test_client()
    assert client.post('/api/v1/admin/users/3/reset-password',json={'new_password':'NewStrong42!'},headers=headers).status_code==404
    assert client.post('/api/v1/admin/users/2/reset-password',json={'new_password':'weak'},headers=headers).status_code==400
    assert client.post('/api/v1/admin/users/2/reset-password',json={'new_password':'NewStrong42!'},headers=headers).status_code==200
    assert client.get('/protected',headers={'Authorization':'Bearer '+peer_access}).status_code==401
    assert client.post('/api/v1/auth/refresh',json={'refresh_token':peer_refresh}).status_code==401
    assert client.get('/protected',headers=headers).status_code==200
    with session_app.app_context():
        assert db.session.get(User,2).token_version==1
        assert db.session.get(User,3).token_version==0
        assert PasswordResetToken.query.filter_by(user_id=2).one().used is True


@pytest.mark.parametrize(('field','value'),[('user_id',True),('user_id',0),('token_version',True),('token_version',-1),('jti','bad'),('iat',None),('iat',True),('iat',0),('iat',1.5),('iat','1')])
def test_bad_preauth_claims_are_rejected(session_app,field,value):
    with session_app.app_context():
        user=db.session.get(User,1);user.two_factor_enabled=True;user.two_factor_secret=pyotp.random_base32();db.session.commit()
        code=pyotp.TOTP(user.two_factor_secret).now()
        signed=TwoFactorService.issue(user)
        claims=jwt.decode(signed,session_app.config['JWT_SECRET_KEY'],algorithms=['HS256']);claims[field]=value
        signed=jwt.encode(claims,session_app.config['JWT_SECRET_KEY'],algorithm='HS256')
    assert session_app.test_client().post('/api/v1/auth/login/2fa',json={'challenge_token':signed,'token':code}).status_code==401
