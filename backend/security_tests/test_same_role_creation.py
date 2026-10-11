"""Pure policy regressions: preserve existing role rules, no identity elevation."""
import pytest
from src.constants.roles import can_user_create_role


@pytest.mark.parametrize('actor,target,flag,allowed', [
    ('supermaster','supermaster',False,False),
    ('supermaster','supermaster',True,True),
    ('master','supermaster',False,False),
    ('master','supermaster',True,False),
    ('affiliate','supermaster',True,False),
    ('trader','supermaster',True,False),
    ('guest','supermaster',True,False),
    ('supermaster','master',False,True),
    ('master','affiliate',False,True),
    ('master','trader',False,True),
    ('affiliate','trader',False,False),
])
def test_same_role_creation_remains_an_explicit_supermaster_capability(actor,target,flag,allowed):
    assert can_user_create_role(actor,target,flag) is allowed
