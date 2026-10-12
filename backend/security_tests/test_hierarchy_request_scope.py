"""Real query/JWT regressions for request hierarchy scope, not full RBAC."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import aliased

from src.database import db
from src.models.user import User
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.user import EmailVerificationToken
from src.utils.decorators import token_required
from src.utils.hierarchy_scoping import (
    init_hierarchy_scoping, set_request_hierarchy_scope, unscoped_query,
    without_hierarchy_scope,
)


@compiles(JSONB,'sqlite')
def _json_sqlite(type_,compiler,**kwargs):
    return 'JSON'


@pytest.fixture
def scope_app(monkeypatch):
    app=Flask('hierarchy-request-regression')
    app.config.update(TESTING=True,SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,JWT_SECRET_KEY='hierarchy-test-only-signing-key-32-bytes',
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        PLATFORM_ROOT_USER_ID=8,EXPANDED_HIERARCHY_ENABLED=True)
    db.init_app(app)
    init_hierarchy_scoping(db,User)
    from src.services import session_service
    monkeypatch.setattr(session_service,'get_redis',lambda:None)
    from src.routes.hierarchy import hierarchy_bp
    from src.routes.admin import admin_bp
    from src.routes.tenants import tenants_bp
    app.register_blueprint(hierarchy_bp,url_prefix='/api/v1/hierarchy')
    app.register_blueprint(admin_bp,url_prefix='/api/v1/admin')
    app.register_blueprint(tenants_bp,url_prefix='/api/v1/tenants')
    import src.routes.admin as admin_routes
    from email_validator import validate_email
    monkeypatch.setattr(admin_routes,'validate_email_format',lambda email:(True,validate_email(email,check_deliverability=False).email))

    @app.get('/visible')
    @token_required
    def visible(current_user):
        users=db.session.execute(select(User.id).order_by(User.id)).scalars().all()
        return jsonify({'ids':users})

    with app.app_context():
        for table in (Tenant.__table__,User.__table__,TokenBlacklist.__table__,EmailVerificationToken.__table__):
            table.create(db.engine)
        db.session.add_all([Tenant(id=1,name='A',subdomain='a'),Tenant(id=2,name='B',subdomain='b')])
        db.session.flush()
        paths={1:('master','1',None,1),2:('master','1/2',1,1),3:('trader','1/2/3',2,1),
            4:('master','1/20',1,1),5:('trader','1/2/5',2,2),6:('supermaster','1/2/6',2,1),
            7:('trader','1/2/6/7',6,1),8:('supermaster','8',None,None),9:('master',None,None,1),
            10:('master','10',None,None),11:('master','r%_\\',None,1),12:('trader','r%_\\/12',11,1),
            13:('trader','rXX\\/13',None,1),14:('trader','1/2',None,1),15:('supermaster',None,None,1)}
        for identity,(role,path,parent,tenant) in paths.items():
            db.session.add(User(id=identity,email=f'scope-{identity}@example.invalid',password_hash='not-a-credential',
                first_name='Scope',last_name='Sentinel',role=role,tree_path=path,parent_id=parent,
                tenant_id=tenant,is_active=True,is_verified=True,can_create_same_role=identity==8))
            db.session.flush()
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        for table in (EmailVerificationToken.__table__,TokenBlacklist.__table__,User.__table__,Tenant.__table__):
            table.drop(db.engine)


def activate(actor):
    principal=db.session.get(User,actor)
    set_request_hierarchy_scope(db.session,principal)
    return principal


@pytest.mark.parametrize('actor,expected',[(2,{2,3,6,7}),(6,{6,7}),(11,{11,12}),(9,set()),(10,set()),(15,set())])
def test_scope_exact_subtree_and_tenant_boundaries(scope_app,actor,expected):
    with scope_app.test_request_context():
        activate(actor)
        assert set(db.session.execute(select(User.id)).scalars())==expected
        alias=aliased(User)
        assert set(db.session.execute(select(alias.id)).scalars())==expected
        assert db.session.execute(select(func.count(User.id))).scalar_one()==len(expected)


@pytest.mark.parametrize('missing',['id','role','tree_path','tenant_id'])
def test_incomplete_principal_cannot_disable_query_filter(scope_app,missing):
    with scope_app.test_request_context():
        fields={'id':2,'role':'master','tree_path':'1/2','parent_id':1,'tenant_id':1}
        fields[missing]=None
        set_request_hierarchy_scope(db.session,SimpleNamespace(**fields))
        assert db.session.execute(select(User.id)).scalars().all()==[]


def test_existing_valid_parentless_supermaster_exemption_not_expanded(scope_app):
    with scope_app.test_request_context():
        activate(8)
        assert db.session.execute(select(func.count(User.id))).scalar_one()==15
    with scope_app.test_request_context():
        activate(6)
        assert set(db.session.execute(select(User.id)).scalars())=={6,7}


def test_query_bypasses_are_explicit_and_context_restores(scope_app):
    with scope_app.test_request_context():
        activate(2)
        with without_hierarchy_scope(db.session):
            assert User.query.count()==15
        assert User.query.count()==4
        assert unscoped_query(User.query).count()==15
        assert User.query.count()==4


def test_listener_registration_does_not_accumulate_per_factory(scope_app):
    handler=db._hierarchy_scope_listener[1]
    for _ in range(5):
        init_hierarchy_scoping(db,User)
        assert db._hierarchy_scope_listener[1] is handler
    with scope_app.test_request_context():
        activate(2)
        assert User.query.count()==4


@pytest.mark.parametrize('operation',['update','delete'])
def test_bulk_orm_mutations_are_constrained_before_sql(scope_app,operation):
    with scope_app.test_request_context():
        activate(2)
        statement=update(User).where(User.id==5).values(first_name='DENIED') if operation=='update' else delete(User).where(User.id==5)
        assert db.session.execute(statement.execution_options(synchronize_session=False)).rowcount==0
        db.session.commit()
    with scope_app.app_context():
        assert db.session.get(User,5).first_name=='Scope'
        assert User.query.count()==15


@pytest.mark.parametrize('actor,expected',[(2,{2,3,6,7}),(6,{6,7}),(9,set()),(10,set()),(15,set())])
def test_http_signed_jwt_revocation_and_real_decorator_feed_scope(scope_app,actor,expected):
    with scope_app.app_context():
        token=db.session.get(User,actor).generate_access_token()
    response=scope_app.test_client().get('/visible',headers={'Authorization':f'Bearer {token}'})
    assert response.status_code==200
    assert set(response.get_json()['ids'])==expected
    assert scope_app.test_client().get('/visible').status_code==401


def test_missing_parent_attribute_never_means_global_root(scope_app):
    with scope_app.test_request_context():
        actor=SimpleNamespace(id=2,role='supermaster',tree_path='1/2',tenant_id=1)
        set_request_hierarchy_scope(db.session,actor)
        assert set(db.session.execute(select(User.id)).scalars())=={2,3,6,7}


def _mvp_owner(app):
    app.config.update(PLATFORM_ROOT_USER_ID=1,EXPANDED_HIERARCHY_ENABLED=False)
    with app.app_context():
        owner=db.session.get(User,1)
        owner.role='supermaster'
        owner.can_create_same_role=True
        db.session.commit()


def _signed_headers(app,identity):
    with app.app_context():
        token=db.session.get(User,identity).generate_access_token()
    return {'Authorization':f'Bearer {token}'}


@pytest.mark.parametrize('identity,status',[(1,200),(2,401),(3,200),(5,401),(6,401),(8,401)])
def test_hierarchy_mvp_session_roles_are_root_users_not_future_managers(scope_app,identity,status):
    _mvp_owner(scope_app)
    response=scope_app.test_client().get('/visible',headers=_signed_headers(scope_app,identity))
    assert response.status_code==status


@pytest.mark.parametrize('configured',[None,True,0,-1,'01','bad','٨'])
def test_hierarchy_unconfigured_or_invalid_owner_never_picks_first_supermaster(scope_app,configured):
    scope_app.config.update(PLATFORM_ROOT_USER_ID=configured,EXPANDED_HIERARCHY_ENABLED=False)
    assert scope_app.test_client().get('/visible',headers=_signed_headers(scope_app,8)).status_code==401


@pytest.mark.parametrize('kind',['blacklist','version'])
def test_hierarchy_actual_routes_reject_real_revoked_jwt(scope_app,kind):
    headers=_signed_headers(scope_app,2)
    token=headers['Authorization'].split()[1]
    with scope_app.app_context():
        if kind=='blacklist':
            from src.services.session_service import SessionService
            db.session.add(SessionService._record(SessionService.payload(token)))
        else:
            db.session.get(User,2).token_version+=1
        db.session.commit()
    response=scope_app.test_client().get('/api/v1/hierarchy/tree',headers=headers)
    assert response.status_code==401
    assert 'tree' not in response.get_json()


def test_hierarchy_offset_is_rejected_before_large_database_work(scope_app):
    response=scope_app.test_client().get('/api/v1/hierarchy/my-direct-team?page=2147483647&per_page=100',headers=_signed_headers(scope_app,2))
    assert response.status_code==400
    assert response.get_json()['code']=='HIERARCHY_OFFSET_TOO_LARGE'


@pytest.mark.parametrize('path,status',[(None,401),('1.2',400),('2%_',400),('/'.join([*(str(1000000000+i) for i in range(45)),'123','1']),400)])
def test_hierarchy_admin_invalid_parent_cannot_leave_committed_account(scope_app,path,status):
    _mvp_owner(scope_app)
    with scope_app.app_context():
        db.session.get(User,1).tree_path=path
        db.session.commit()
    response=scope_app.test_client().post('/api/v1/admin/users',headers=_signed_headers(scope_app,1),json={
        'email':'atomic-child@example.com','password':'ValidPassword!2026','first_name':'Atomic','last_name':'Child','role':'trader'})
    assert response.status_code==status
    with scope_app.app_context():
        assert User.query.count()==15
        assert User.query.filter_by(email='atomic-child@example.com').first() is None


def test_hierarchy_admin_creation_is_owned_canonical_and_has_no_new_capability(scope_app):
    _mvp_owner(scope_app)
    payload={'email':'atomic-child@example.com','password':'ValidPassword!2026',
        'first_name':'Atomic','last_name':'Child','role':'trader'}
    rejected=scope_app.test_client().post('/api/v1/admin/users',headers=_signed_headers(scope_app,1),
        json={**payload,'can_create_same_role':True})
    assert rejected.status_code==400
    with scope_app.app_context():
        assert User.query.count()==15
        assert User.query.filter_by(email=payload['email']).first() is None
    response=scope_app.test_client().post('/api/v1/admin/users',headers=_signed_headers(scope_app,1),json=payload)
    assert response.status_code==201
    with scope_app.app_context():
        child=User.query.filter_by(email='atomic-child@example.com').one()
        assert child.tenant_id==1 and child.parent_id==1
        assert child.tree_path==f'1/{child.id}'
        assert child.can_create_same_role is False


def test_hierarchy_mvp_owner_cannot_create_future_manager_or_another_root(scope_app):
    _mvp_owner(scope_app)
    with scope_app.app_context():
        owner=db.session.get(User,1)
        assert owner.can_create_user('trader') and owner.can_create_user('affiliate')
        assert not owner.can_create_user('master') and not owner.can_create_user('supermaster')
        assert not db.session.get(User,2).can_create_user('trader')


def test_hierarchy_registration_selects_configured_owner_and_brand_once(scope_app):
    _mvp_owner(scope_app)
    from src.services.auth_service import AuthService
    with scope_app.app_context():
        user,verification=AuthService.register_user('register@example.invalid','ValidPassword!2026','Registered','User')
        assert user.parent_id==1 and user.tenant_id==1 and user.role=='trader'
        assert user.tree_path==f'1/{user.id}'
        assert verification.user_id==user.id
        assert User.query.count()==16 and EmailVerificationToken.query.count()==1


@pytest.mark.parametrize('case',['owner_unconfigured','brand_unknown','verification_failure','cross_brand','role_injection'])
def test_hierarchy_registration_failure_has_no_partial_account(scope_app,monkeypatch,case):
    _mvp_owner(scope_app)
    from src.services import auth_service
    kwargs={}
    if case=='owner_unconfigured':scope_app.config['PLATFORM_ROOT_USER_ID']=None
    with scope_app.app_context():
        if case=='brand_unknown':
            db.session.get(User,1).tenant_id=None
            db.session.commit()
        if case=='verification_failure':
            def fail_verification(user_id):raise ValueError('Synthetic late-stage failure')
            monkeypatch.setattr(auth_service,'EmailVerificationToken',fail_verification)
        if case=='cross_brand':kwargs['tenant_id']=2
        if case=='role_injection':kwargs['role']='supermaster'
        with pytest.raises(ValueError):
            auth_service.AuthService.register_user('rejected@example.invalid','ValidPassword!2026','Rejected','User',**kwargs)
        assert User.query.count()==15 and EmailVerificationToken.query.count()==0
        assert User.query.filter_by(email='rejected@example.invalid').first() is None


def test_hierarchy_referral_collision_retries_are_finite(scope_app,monkeypatch):
    with scope_app.app_context():
        existing=db.session.get(User,1)
        existing.referral_code='AAAAAAAA'
        db.session.commit()
        calls=[]
        import secrets
        monkeypatch.setattr(secrets,'choice',lambda choices:(calls.append(1) or 'A'))
        candidate=db.session.get(User,2)
        before=candidate.referral_code
        with pytest.raises(RuntimeError,match='unique referral code'):
            candidate.generate_referral_code()
        assert len(calls)==32*8
        assert candidate.referral_code==before


@pytest.mark.parametrize('path',['/api/v1/hierarchy/tree','/api/v1/tenants/'])
def test_hierarchy_mvp_keeps_future_products_disabled(scope_app,path):
    _mvp_owner(scope_app)
    response=scope_app.test_client().get(path,headers=_signed_headers(scope_app,1))
    assert response.status_code==409
    assert response.get_json()['code'] in {'WHITE_LABEL_DISABLED','EXPANDED_HIERARCHY_DISABLED'}


def test_hierarchy_mvp_public_brand_is_owner_brand_not_header_fallback(scope_app):
    _mvp_owner(scope_app)
    response=scope_app.test_client().get('/api/v1/tenants/current',headers={'X-Tenant-ID':'2','Host':'b.example.invalid'})
    assert response.status_code==200
    assert response.get_json()['tenant']['id']==1
    with scope_app.app_context():
        db.session.get(User,1).tenant_id=None
        db.session.commit()
    response=scope_app.test_client().get('/api/v1/tenants/current')
    assert response.status_code==503 and response.get_json()['code']=='BRAND_NOT_CONFIGURED'
    assert scope_app.test_client().get('/visible',headers=_signed_headers(scope_app,3)).status_code==401


def test_hierarchy_mvp_new_affiliate_is_not_activated_with_legacy_bonus_default(scope_app):
    _mvp_owner(scope_app)
    response=scope_app.test_client().post('/api/v1/admin/users',headers=_signed_headers(scope_app,1),json={
        'email':'affiliate@example.com','password':'ValidPassword!2026','first_name':'Affiliate','last_name':'Pending','role':'affiliate'})
    assert response.status_code==409
    assert response.get_json()['code']=='AFFILIATE_PROGRAM_NOT_CONFIGURED'
    with scope_app.app_context():assert User.query.count()==15


@pytest.mark.parametrize('role,active,allowed',[('affiliate',True,True),('agent',True,True),('master',True,False),('affiliate',False,False)])
def test_hierarchy_mvp_referral_registration_owns_brand_without_minting_bonus(scope_app,monkeypatch,role,active,allowed):
    _mvp_owner(scope_app)
    from src.models.agent import Agent
    from src.models.referral import Referral
    from src.services.auth_service import AuthService
    from src.services.email_service import EmailService
    monkeypatch.setattr(EmailService,'send_new_downline_email',lambda *args:None)
    with scope_app.app_context():
        Agent.__table__.create(db.engine)
        Referral.__table__.create(db.engine)
        affiliate=db.session.get(User,2)
        affiliate.role=role
        affiliate.is_active=active
        profile=Agent(user_id=2,agent_code='AFF_TEST',commission_rate=0,is_active=True)
        db.session.add(profile)
        db.session.commit()
        if allowed:
            user,_=AuthService.register_user('via-affiliate@example.invalid','ValidPassword!2026','Via','Affiliate',referral_code='AFF_TEST')
            assert user.parent_id==2 and user.tenant_id==1
            referral=Referral.query.one()
            assert referral.agent_id==profile.id and referral.referred_user_id==user.id and referral.status=='pending'
            assert profile.referral_count==1 and profile.total_earned==0 and profile.pending_balance==0
        else:
            with pytest.raises(ValueError):
                AuthService.register_user('via-affiliate@example.invalid','ValidPassword!2026','Via','Affiliate',referral_code='AFF_TEST')
            assert User.query.count()==15 and Referral.query.count()==0 and profile.referral_count==0
        Referral.__table__.drop(db.engine)
        Agent.__table__.drop(db.engine)
