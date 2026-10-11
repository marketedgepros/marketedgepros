import pytest
from flask import g, jsonify
from src.database import db
from src.models.user import User
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.utils.decorators import token_required, role_required


@pytest.fixture
def contract_app():
    from src.app import create_app
    app=create_app('testing',config_overrides={'EXPANDED_HIERARCHY_ENABLED':False,'PLATFORM_ROOT_USER_ID':1,
                                             'PROPAGATE_EXCEPTIONS':False,'RATELIMIT_ENABLED':False})
    calls=[]
    app.contract_calls=calls

    @app.get('/contract/g/<int:resource_id>')
    @token_required
    @role_required('trader')
    def g_handler(resource_id):
        calls.append('g')
        return jsonify(identity=g.current_user.id,resource=resource_id)

    @app.get('/contract/explicit/<int:resource_id>')
    @token_required
    def explicit_handler(current_user,resource_id):
        calls.append('explicit')
        return jsonify(identity=current_user.id,resource=resource_id)

    @app.get('/contract/alias/<int:resource_id>')
    @token_required
    def alias_handler(user,resource_id):
        calls.append('alias')
        return jsonify(identity=user.id,resource=resource_id)

    @app.get('/contract/keyword/<int:resource_id>')
    @token_required
    def keyword_handler(resource_id,*,current_user):
        calls.append('keyword')
        return jsonify(identity=current_user.id,resource=resource_id)

    @app.get('/contract/error')
    @token_required
    def intentional_error(current_user):
        calls.append('error')
        raise TypeError('Synthetic handler failure: never retry this call')

    with app.app_context():
        db.metadata.create_all(bind=db.engine,tables=[Tenant.__table__,User.__table__,TokenBlacklist.__table__])
        db.session.add(Tenant(id=1,name='Synthetic Brand',subdomain='synthetic',status='active'))
        db.session.add(Tenant(id=2,name='Other Synthetic Brand',subdomain='other',status='active'))
        db.session.add_all([
            User(id=1,email='owner@example.invalid',password_hash='not-a-credential',first_name='Owner',last_name='Synthetic',
                 role='supermaster',parent_id=None,tree_path='1',level=0,tenant_id=1,is_active=True,is_verified=True,can_create_same_role=True),
            User(id=2,email='user@example.invalid',password_hash='not-a-credential',first_name='User',last_name='Synthetic',
                 role='trader',parent_id=1,tree_path='1/2',level=1,tenant_id=1,is_active=True,is_verified=True,can_create_same_role=False),
        ])
        for identity,role,tenant,parent,path in [(3,'affiliate',1,1,'1/3'),(4,'trader',2,1,'1/4'),
                                               (5,'master',1,1,'1/5'),(6,'supermaster',1,None,'6')]:
            db.session.add(User(id=identity,email=f'actor-{identity}@example.invalid',password_hash='not-a-credential',
                                first_name='Synthetic',last_name='Actor',role=role,tenant_id=tenant,parent_id=parent,
                                tree_path=path,level=0 if parent is None else 1,is_active=True,is_verified=True,
                                can_create_same_role=identity==6))
        db.session.commit()
        app.contract_token=db.session.get(User,2).generate_access_token()
    yield app
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine,tables=[TokenBlacklist.__table__,User.__table__,Tenant.__table__])


@pytest.mark.parametrize('style',['g','explicit','keyword','alias'])
def test_authenticated_http_styles_preserve_principal_and_url_arguments(contract_app,style):
    response=contract_app.test_client().get('/contract/'+style+'/42',headers={'Authorization':'Bearer '+contract_app.contract_token})
    assert response.status_code==200 and response.get_json()=={'identity':2,'resource':42}
    assert contract_app.contract_calls==[style]


def test_failed_handler_is_not_retried(contract_app):
    response=contract_app.test_client().get('/contract/error',headers={'Authorization':'Bearer '+contract_app.contract_token})
    assert response.status_code==500 and contract_app.contract_calls==['error']


def test_missing_auth_never_invokes_handler(contract_app):
    assert contract_app.test_client().get('/contract/g/42').status_code==401
    assert contract_app.contract_calls==[]


def test_actual_g_style_user_profile_and_legacy_tree_gate(contract_app):
    headers={'Authorization':'Bearer '+contract_app.contract_token}
    response=contract_app.test_client().get('/api/v1/users/profile',headers=headers)
    assert response.status_code==200 and response.get_json()['id']==2
    response=contract_app.test_client().get('/api/v1/users/hierarchy',headers=headers)
    assert response.status_code==409 and response.get_json()['code']=='EXPANDED_HIERARCHY_DISABLED'


def test_inactive_brand_denies_existing_ordinary_session_and_public_brand(contract_app):
    with contract_app.app_context():
        db.session.get(Tenant,1).status='inactive'
        db.session.commit()
    headers={'Authorization':'Bearer '+contract_app.contract_token}
    assert contract_app.test_client().get('/api/v1/users/profile',headers=headers).status_code==401
    assert contract_app.test_client().get('/api/v1/tenants/current').status_code==503


@pytest.mark.parametrize('identity,path,status',[
    (1,'/api/v1/admin/users',200),(2,'/api/v1/admin/users',403),(3,'/api/v1/admin/users',403),
    (2,'/api/v1/users/profile',200),(3,'/api/v1/users/profile',200),
    (4,'/api/v1/users/profile',401),(5,'/api/v1/users/profile',401),(6,'/api/v1/users/profile',401),
    (4,'/api/v1/admin/users',401),(5,'/api/v1/admin/users',401),(6,'/api/v1/admin/users',401),
])
def test_full_factory_mvp_role_action_brand_matrix(contract_app,identity,path,status):
    with contract_app.app_context():
        token=db.session.get(User,identity).generate_access_token()
    response=contract_app.test_client().get(path,headers={'Authorization':'Bearer '+token})
    assert response.status_code==status
    if status==200 and path.endswith('/profile'):
        assert response.get_json()['id']==identity


@pytest.mark.parametrize('case',['inactive','unmapped'])
def test_designated_root_has_no_global_access_without_active_configured_brand(contract_app,case):
    with contract_app.app_context():
        owner=db.session.get(User,1)
        token=owner.generate_access_token()
        if case=='inactive':db.session.get(Tenant,1).status='inactive'
        else:owner.tenant_id=None
        db.session.commit()
    response=contract_app.test_client().get('/api/v1/admin/users',headers={'Authorization':'Bearer '+token})
    assert response.status_code==401
    assert contract_app.test_client().get('/api/v1/tenants/current').status_code==503
    assert contract_app.test_client().get('/health').status_code==200
