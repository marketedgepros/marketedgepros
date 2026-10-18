"""No activation, SQL or provider authority outside the private rehearsal."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta

from flask import Flask
import pytest

from src.database import db
from src.services.affiliate_lifecycle_contract import AffiliatePolicy, LifecycleError, decode_policy
from src.services.affiliate_lifecycle_service import AffiliateLifecycleRehearsal as Service

AT = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
ID = '12345678-1234-1234-1234-123456789abc'


def policy(**changes):
    values = dict(version='TST_LIFECYCLE_1', rate_basis_points=1500, basis='paid_order_total',
                  currency='USD', hold_seconds=3600, minimum_payout_minor=100, rounding='floor', mode='synthetic')
    values.update(changes)
    return AffiliatePolicy(**values)


def calls():
    return (
        lambda: Service.record_identity(1, 1, 'a' * 64, 'SYNTHETIC_1', at=AT),
        lambda: Service.attribute_order(ID, 2, ID, ID, policy(), at=AT),
        lambda: Service.accrue(ID, ID, at=AT),
        lambda: Service.review(ID, True, at=AT),
        lambda: Service.release(ID, at=AT),
        lambda: Service.reverse(ID, 'SYNTHETIC_REFUND', at=AT),
        lambda: Service.prepare_payout(ID, 1, 'SYNTHETIC_NET', 'SYNTHETIC_ASSET', 'b' * 64, 12345, 'c' * 64, at=AT),
        lambda: Service.claim_payout(ID, at=AT),
        lambda: Service.mark_uncertain(ID, ID, at=AT),
        lambda: Service.confirm_payout(ID, ID, 'SYNTHETIC_TRANSFER', at=AT),
    )


@pytest.mark.parametrize('testing,enabled,inner,flask_testing', [
    (False, True, '1', 'true'), (True, False, '1', 'true'), (True, 1, '1', 'true'),
    (True, True, None, 'true'), (True, True, '1', 'false'),
])
def test_every_operation_refuses_before_engine_or_sql(monkeypatch, testing, enabled, inner, flask_testing):
    app = Flask('affiliate-isolation-canary')
    app.config.update(TESTING=testing, AFFILIATE_LIFECYCLE_REHEARSAL_ENABLED=enabled)
    monkeypatch.setenv('FLASK_TESTING', flask_testing)
    if inner is None:
        monkeypatch.delenv('MARKETEDGEPROS_STAGING_INNER', raising=False)
    else:
        monkeypatch.setenv('MARKETEDGEPROS_STAGING_INNER', inner)
    def forbidden(*args, **kwargs):
        raise AssertionError('Engine/SQL reached without isolation')
    monkeypatch.setattr(db.session, 'get_bind', forbidden)
    monkeypatch.setattr(db.session, 'execute', forbidden)
    with app.app_context():
        for call in calls():
            with pytest.raises(LifecycleError) as error:
                call()
            assert (error.value.code, error.value.status) == ('AFFILIATE_NOT_CONFIGURED', 503)


@pytest.mark.parametrize('target', ['postgresql://remote.invalid/production', 'sqlite:///:memory:',
                                     'postgresql+psycopg2://test@/marketedgepros_test_fake?host=/tmp'])
def test_forged_runner_refuses_unsafe_target_before_engine(monkeypatch, target):
    app = Flask('affiliate-forged-runner')
    app.config.update(TESTING=True, AFFILIATE_LIFECYCLE_REHEARSAL_ENABLED=True,
                      SQLALCHEMY_DATABASE_URI=target, ISOLATED_STAGING_DATABASE=True)
    monkeypatch.setenv('FLASK_TESTING', 'true')
    monkeypatch.setenv('MARKETEDGEPROS_STAGING_INNER', '1')
    for name in ('STAGING_RUN_ROOT', 'STAGING_PG_SOCKET', 'STAGING_PG_PORT', 'STAGING_RUNTIME_USER'):
        monkeypatch.delenv(name, raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('Engine/SQL reached before private socket validation')
    monkeypatch.setattr(db.session, 'get_bind', forbidden)
    monkeypatch.setattr(db.session, 'execute', forbidden)
    with app.app_context():
        for call in calls():
            with pytest.raises(LifecycleError) as error:
                call()
            assert (error.value.code, error.value.status) == ('AFFILIATE_ISOLATION_REQUIRED', 503)


def test_no_default_activation_and_no_new_public_endpoint():
    from src.config import Config, TestingConfig, DevelopmentConfig, ProductionConfig
    assert all(cls.AFFILIATE_LIFECYCLE_REHEARSAL_ENABLED is False for cls in
               (Config, TestingConfig, DevelopmentConfig, ProductionConfig))
    from src.app import create_app
    app = create_app('testing')
    assert not any('lifecycle' in rule.rule for rule in app.url_map.iter_rules())


@pytest.mark.parametrize('field,value', [
    ('rate_basis_points', True), ('rate_basis_points', 15.0), ('rate_basis_points', 0), ('rate_basis_points', 10001),
    ('hold_seconds', False), ('hold_seconds', -1), ('hold_seconds', 31536001),
    ('minimum_payout_minor', 0), ('minimum_payout_minor', '100'), ('minimum_payout_minor', 1.5),
    ('basis', 'net_after_tax'), ('mode', 'live'), ('currency', 'USDT'), ('rounding', 'ceil'),
    ('version', ''), ('version', 'x' * 65), ('version', 'é'),
])
def test_policy_requires_exact_explicit_supported_fields(field, value):
    with pytest.raises(LifecycleError) as error:
        policy(**{field: value})
    assert error.value.code == 'AFFILIATE_INVALID'


def test_policy_no_defaults_floor_rounding_and_fingerprint_integrity():
    with pytest.raises(TypeError):
        AffiliatePolicy()
    p = policy()
    assert p.commission_minor(1999) == 299
    assert decode_policy(p.canonical_dict(), p.digest) == p
    changed = replace(p, hold_seconds=3601)
    assert changed.digest != p.digest
    with pytest.raises(LifecycleError) as error:
        decode_policy(changed.canonical_dict(), p.digest)
    assert error.value.code == 'AFFILIATE_STORAGE_NOT_READY'
    with pytest.raises(LifecycleError) as error:
        p.commission_minor(1)
    assert error.value.code == 'AFFILIATE_ZERO_AWARD'


@pytest.mark.parametrize('value', [True, 1.0, '1999', 0, 10000000000])
def test_commission_does_not_coerce_amount(value):
    with pytest.raises(LifecycleError):
        policy().commission_minor(value)


@pytest.mark.parametrize('value', [AT.replace(tzinfo=None), AT.astimezone(timezone(timedelta(hours=1))),
                                   AT.replace(fold=1), '2026-10-12'])
def test_timestamp_requires_canonical_utc(value):
    from src.services.affiliate_lifecycle_contract import utc_datetime
    with pytest.raises(LifecycleError):
        utc_datetime(value)


def test_forged_frozen_dataclass_still_revalidates():
    p = policy()
    object.__setattr__(p, 'mode', 'live')
    with pytest.raises(LifecycleError):
        p.canonical_dict()
    with pytest.raises(LifecycleError):
        p.commission_minor(1999)


def test_affiliate_runtime_modules_do_not_import_migration_code():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for relative in ['src/services/affiliate_lifecycle_service.py', 'src/services/affiliate_lifecycle_storage.py',
                     'src/isolated_postgresql_target.py', 'src/testing_safety.py']:
        tree = ast.parse((root / relative).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith('migrations'), relative
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith('migrations') for alias in node.names), relative
