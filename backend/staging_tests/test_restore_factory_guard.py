import copy
import os
import pytest
from sqlalchemy import text
from src.testing_safety import validate_testing_resources
from src.services.launch_reconciliation_service import plan_single_brand_reconciliation, apply_plan_to_isolated_copy, ReconciliationRefused


def resource_config(url):
    return {'TESTING':True,'SQLALCHEMY_DATABASE_URI':url,'ISOLATED_STAGING_DATABASE':True,
            'CACHE_TYPE':'SimpleCache','REDIS_URL':None,'RATELIMIT_STORAGE_URL':'memory://'}


def test_socket_factory_is_opt_in_and_runner_resource_validated(staging_resources,monkeypatch):
    url=staging_resources['pg_url']
    monkeypatch.setenv('TEST_DATABASE_URL',url)
    config=resource_config(url)
    validate_testing_resources(config)
    config['ISOLATED_STAGING_DATABASE']=False
    with pytest.raises(ValueError,match='loopback'):validate_testing_resources(config)
    config['ISOLATED_STAGING_DATABASE']=True
    monkeypatch.delenv('STAGING_RUN_ROOT')
    with pytest.raises(RuntimeError):validate_testing_resources(config)


@pytest.mark.parametrize('field,value',[('REDIS_URL','redis://localhost'),('SQLALCHEMY_BINDS',{'other':'postgresql://localhost/production'}),('SQLALCHEMY_ENGINE_OPTIONS',{'creator':lambda:None})])
def test_socket_opt_in_does_not_bypass_other_resource_guards(staging_resources,monkeypatch,field,value):
    monkeypatch.setenv('TEST_DATABASE_URL',staging_resources['pg_url'])
    config=resource_config(staging_resources['pg_url']);config[field]=value
    with pytest.raises(ValueError):validate_testing_resources(config)


def test_reconciliation_stale_preimage_refuses_before_any_update(app):
    from src.database import db
    from src.models.user import User
    from src.models.tenant import Tenant
    with app.app_context():
        db.session.add(Tenant(id=10,name='Synthetic Brand',subdomain='synthetic',status='active'))
        db.session.add_all([
            User(id=1,email='owner@example.invalid',password_hash='not-a-credential',first_name='Owner',last_name='Test',role='supermaster',
                 parent_id=None,tree_path='1',level=0,tenant_id=None,is_active=True,is_verified=True,can_create_same_role=True,token_version=3),
            User(id=2,email='user@example.invalid',password_hash='not-a-credential',first_name='User',last_name='Test',role='trader',
                 parent_id=1,tree_path='1.2',level=1,tenant_id=None,is_active=True,is_verified=True,can_create_same_role=False,token_version=0),
        ])
        db.session.commit()
        with db.engine.connect() as con:
            users=[row[0] for row in con.execute(text('SELECT to_jsonb(t) FROM users t'))]
            tenants=[row[0] for row in con.execute(text('SELECT to_jsonb(t) FROM tenants t'))]
        plan=plan_single_brand_reconciliation(users,tenants,[],[],owner_id=1,brand_id=10)
        assert len(plan['changes'])==2
        with db.engine.begin() as con:
            con.execute(text("UPDATE users SET tree_path='1.changed' WHERE id=2"))
        with pytest.raises(ReconciliationRefused):
            with db.engine.begin() as con:apply_plan_to_isolated_copy(con,plan)
        with db.engine.connect() as con:
            assert tuple(con.execute(text('SELECT tenant_id,tree_path,token_version FROM users WHERE id=1')).one())==(None,'1',3)
            assert tuple(con.execute(text('SELECT tenant_id,tree_path,token_version FROM users WHERE id=2')).one())==(None,'1.changed',0)
