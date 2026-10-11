import copy
import pytest
from src.services.launch_reconciliation_service import (
    ReconciliationRefused, plan_single_brand_reconciliation, apply_plan_to_isolated_copy,
)


def dataset():
    owner=dict(id=1,role='supermaster',parent_id=None,tree_path='1',level=0,tenant_id=None,
               is_active=True,is_verified=True,can_create_same_role=True,token_version=3)
    user=dict(id=2,role='trader',parent_id=1,tree_path='1.2',level=1,tenant_id=None,
              is_active=True,is_verified=False,can_create_same_role=False,token_version=0,
              available_balance=None,kyc_status='pending')
    other=dict(id=3,role='trader',parent_id=1,tree_path='1.3',level=1,tenant_id=99,
               is_active=True,is_verified=True,can_create_same_role=False,token_version=0)
    return [owner,user,other],[dict(id=10,status='active')],[dict(id=20,user_id=2,program_id=30,status='pending')],[dict(id=30,tenant_id=10)]


def plan(d):
    return plan_single_brand_reconciliation(*d,owner_id=1,brand_id=10)


def test_plan_is_pure_exact_and_preserves_other_brands_and_unverified_status():
    d=dataset();before=copy.deepcopy(d);p=plan(d)
    assert d==before
    assert len(p['changes'])==2
    assert p['changes'][0]['after']==dict(tenant_id=10,tree_path='1',token_version=4)
    assert p['changes'][1]['after']==dict(tenant_id=10,tree_path='1/2',token_version=1)
    assert p['excluded']==[dict(user_id=3,reason='existing_other_brand')]
    assert d[0][1]['is_verified'] is False and d[0][1]['available_balance'] is None


@pytest.mark.parametrize('field,value',[('is_verified',False),('is_active',False),('can_create_same_role',False),('role','master'),('tree_path','x'),('parent_id',7),('tenant_id',99)])
def test_ineligible_owner_never_gets_a_repair_plan(field,value):
    d=dataset();d[0][0][field]=value
    with pytest.raises(ReconciliationRefused):plan(d)


@pytest.mark.parametrize('kind',['path','depth','cycle','other_brand_parent','unknown_parent','foreign_challenge','unknown_program','inactive_brand','token_unknown','token_boolean'])
def test_ambiguous_ownership_is_refused_without_mutation(kind):
    d=dataset()
    if kind=='path':d[0][1]['tree_path']='1.999'
    elif kind=='depth':d[0][1]['level']=3
    elif kind=='cycle':d[0][1]['parent_id']=2
    elif kind=='other_brand_parent':d[0][1]['parent_id']=3
    elif kind=='unknown_parent':d[0][1]['parent_id']=999
    elif kind=='foreign_challenge':d[3][0]['tenant_id']=99
    elif kind=='unknown_program':d[2][0]['program_id']=999
    elif kind=='inactive_brand':d[1][0]['status']='inactive'
    elif kind=='token_unknown':d[0][1]['token_version']=None
    elif kind=='token_boolean':d[0][1]['token_version']=True
    before=copy.deepcopy(d)
    with pytest.raises(ReconciliationRefused):plan(d)
    assert d==before


def test_application_refuses_an_arbitrary_database_before_sql():
    class Engine:
        class URL:
            def render_as_string(self,**kwargs):return 'postgresql://localhost/production'
        url=URL()
    class Connection:
        engine=Engine()
        def execute(self,*args):pytest.fail('SQL before guard')
    with pytest.raises(RuntimeError):apply_plan_to_isolated_copy(Connection(),plan(dataset()))


def test_applied_plan_is_idempotent_and_does_not_change_roles():
    d=dataset();p=plan(d)
    for c in p['changes']:
        next(u for u in d[0] if u['id']==c['user_id']).update(c['after'])
    assert plan(d)['changes']==[]
    assert [u['role'] for u in d[0]]==['supermaster','trader','trader']
