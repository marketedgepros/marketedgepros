"""Approved symbol-optional policy; synthetic passwords only, no network."""
import pytest
from pathlib import Path
from marshmallow import ValidationError
from src.schemas.auth_schemas import RegisterSchema, PasswordResetSchema
from src.services.auth_token_service import AuthTokenService
from src.services.admin_closure_users import _password_input, AdminClosureUsersValidationError
from src.utils.validators import validate_password_strength


@pytest.mark.parametrize('password', ['SyntheticPass7', 'SyntheticPass7!'])
def test_symbol_optional_across_all_active_validators(password):
    assert validate_password_strength(password)[0]
    assert AuthTokenService._password(password) == password
    assert _password_input({'new_password': password}) == password
    assert RegisterSchema().load({'email': 'policy@example.com', 'password': password,
                                  'first_name': 'Policy', 'last_name': 'Fixture'})['password'] == password
    assert PasswordResetSchema().load({'email': 'policy@example.com', 'code': '123456',
                                       'new_password': password})['new_password'] == password


@pytest.mark.parametrize('password', ['Abc12', 'syntheticpass7', 'SYNTHETICPASS7', 'SyntheticPass', '1234567890'])
def test_other_requirements_still_enforced_everywhere(password):
    assert not validate_password_strength(password)[0]
    with pytest.raises(ValueError):
        AuthTokenService._password(password)
    with pytest.raises(AdminClosureUsersValidationError):
        _password_input({'new_password': password})
    with pytest.raises(ValidationError):
        RegisterSchema().load({'email': 'policy@example.com', 'password': password,
                               'first_name': 'Policy', 'last_name': 'Fixture'})
    with pytest.raises(ValidationError):
        PasswordResetSchema().load({'email': 'policy@example.com', 'code': '123456', 'new_password': password})


def test_existing_maximum_limits_preserved():
    password = 'SyntheticPass7' + 'a' * 1030
    with pytest.raises(ValueError):
        AuthTokenService._password(password)
    with pytest.raises(AdminClosureUsersValidationError):
        _password_input({'new_password': password})
    with pytest.raises(ValidationError):
        PasswordResetSchema().load({'email': 'policy@example.com', 'code': '123456', 'new_password': password})


def test_unloaded_legacy_input_validator_keeps_other_flags_and_optional_symbol():
    # This module's unrelated bleach/validators dependencies are not runtime inputs.
    # Do not add dependencies or pretend that it is an active authentication path.
    source = (Path(__file__).resolve().parents[1] / 'src/utils/input_validation.py').read_text()
    assert 'PASSWORD_REQUIRE_SPECIAL = False' in source
    for flag in ['UPPERCASE', 'LOWERCASE', 'DIGIT']:
        assert f'PASSWORD_REQUIRE_{flag} = True' in source
    assert 'PASSWORD_MIN_LENGTH = 8' in source
    assert 'PASSWORD_MAX_LENGTH = 128' in source
