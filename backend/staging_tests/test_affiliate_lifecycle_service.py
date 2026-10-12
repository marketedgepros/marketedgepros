"""Private-PostgreSQL integration rehearsal for the synthetic affiliate lifecycle.

Run only through backend/scripts/run_staging_integration.py.  It creates a fresh
runner-private database and upgrades it with Alembic; it never uses create_all,
provider calls, KYC evidence, funds, HTTP routes, or production resources.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from threading import Barrier
from time import monotonic
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from flask import Flask
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError


HEAD = "20261012_000001"
UTC = timezone.utc
ORDER_AT = datetime(2026, 10, 12, 11, 0, tzinfo=UTC)
IDENTITY_AT = datetime(2026, 10, 12, 11, 30, tzinfo=UTC)
ATTRIBUTION_AT = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
RECEIPT_AT = datetime(2026, 10, 12, 12, 1, tzinfo=UTC)
ACCRUAL_AT = datetime(2026, 10, 12, 12, 2, tzinfo=UTC)
RELEASE_AT = RECEIPT_AT + timedelta(seconds=3600)
BUYER_HASH, AFFILIATE_HASH, OTHER_HASH = "a" * 64, "b" * 64, "c" * 64
RECIPIENT_HASH, QUOTE_HASH = "d" * 64, "e" * 64


def uid(value):
    return f"00000000-0000-0000-0000-{value:012d}"


@contextmanager
def lifecycle_database(resources, monkeypatch):
    """Fresh isolated database migrated to the exact affiliate head, no ORM DDL."""
    from src.app import create_app
    from src.database import db

    database = "marketedgepros_test_" + uuid4().hex
    url = make_url(resources["pg_url"]).set(database=database)
    rendered = url.render_as_string(hide_password=False)
    admin = create_engine(make_url(resources["pg_url"]).set(database="postgres"),
                          isolation_level="AUTOCOMMIT")
    app = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        monkeypatch.setenv("TEST_DATABASE_URL", rendered)
        backend = Path(__file__).resolve().parents[1]
        config = Config(str(backend / "migrations" / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "migrations"))
        config.set_main_option("sqlalchemy.url", rendered.replace("%", "%%"))
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, HEAD)
        finally:
            engine.dispose()
        app = create_app("testing", config_overrides={
            "SQLALCHEMY_DATABASE_URI": rendered,
            "ISOLATED_STAGING_DATABASE": True,
            "AFFILIATE_LIFECYCLE_REHEARSAL_ENABLED": True,
            "PLATFORM_ROOT_USER_ID": 1,
            "EXPANDED_HIERARCHY_ENABLED": False,
            "SQLALCHEMY_ENGINE_OPTIONS": {"pool_size": 6, "max_overflow": 0, "pool_timeout": 5},
        })
        with app.app_context():
            seed_legacy()
            db.session.commit()
            assert db.session.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == [HEAD]
        yield app
    finally:
        if app is not None:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def lifecycle_app(staging_resources, monkeypatch):
    with lifecycle_database(staging_resources, monkeypatch) as app:
        yield app


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def seed_legacy():
    """Only explicit synthetic tenants/users/programs and immutable valid quotes."""
    from src.database import db

    db.session.execute(text("""INSERT INTO tenants (id,name,slug,subdomain,status) VALUES
        (1,'Synthetic Lifecycle Tenant','synthetic-lifecycle','synthetic-lifecycle','active'),
        (2,'Synthetic Foreign Tenant','synthetic-foreign','synthetic-foreign','active')"""))
    db.session.execute(text("""INSERT INTO users
        (id,email,password_hash,first_name,last_name,role,tenant_id,parent_id,level,tree_path,is_active,is_verified,can_create_same_role)
        VALUES
        (1,'synthetic-root@affiliate.invalid','not-a-credential','Synthetic','Root','supermaster',1,NULL,0,'1',true,true,true),
        (2,'synthetic-buyer@affiliate.invalid','not-a-credential','Synthetic','Buyer','trader',1,1,1,'1/2',true,true,false),
        (3,'synthetic-affiliate@affiliate.invalid','not-a-credential','Synthetic','Affiliate','trader',1,1,1,'1/3',true,true,false),
        (4,'synthetic-same-subject@affiliate.invalid','not-a-credential','Synthetic','SameSubject','trader',1,1,1,'1/4',true,true,false),
        (5,'synthetic-foreign@affiliate.invalid','not-a-credential','Synthetic','Foreign','trader',2,NULL,0,'5',true,true,false)"""))
    db.session.execute(text("""INSERT INTO trading_programs
        (id,tenant_id,name,program_type,type,account_size,price,rules,is_active,profit_target,max_daily_loss,max_total_loss,profit_split)
        VALUES (10,1,'Synthetic Lifecycle Program','one_phase','one_phase',10000,19.99,
        CAST(:rules AS jsonb),true,10,5,10,80),
        (20,2,'Synthetic Foreign Program','one_phase','one_phase',10000,19.99,
        CAST(:rules AS jsonb),true,10,5,10,80)"""), {"rules": '{"source":"synthetic","local_only":true}'})
    for sequence, amount in ((1, 1001), (2, 1001), (3, 1001), (4, 1001), (5, 1), (6, 1001)):
        seed_order(sequence, amount)


def seed_order(sequence, amount, user_id=2, tenant_id=1, program_id=10):
    """A valid immutable legacy quote; no old row is altered for chronology."""
    from src.database import db

    amount_text = f"{amount // 100}.{amount % 100:02d}"
    snapshot = {
        "schema": 1, "kind": "purchase_quote", "user_id": user_id, "tenant_id": tenant_id,
        "program_id": program_id, "currency": "USD", "base_amount": amount_text,
        "addons": [], "amount": amount_text,
        "rounding": "USD cents; ROUND_HALF_UP per add-on line", "terms": {"synthetic": True},
        "settlement": "not_configured", "entitlement": False,
    }
    snapshot_json = canonical(snapshot)
    db.session.execute(text("""INSERT INTO purchase_orders
        (id,user_id,tenant_id,program_id,idempotency_key,request_hash,snapshot_hash,snapshot_json,amount_minor,currency,state,created_at)
        VALUES (:id,:user,:tenant,:program,:key,:request,:snapshot_hash,:snapshot,:amount,'USD','quoted',:created)"""), {
        "id": uid(100 + sequence), "user": user_id, "tenant": tenant_id, "program": program_id,
        "key": f"synthetic_lifecycle_quote_{sequence:04d}",
        "request": (f"{sequence:x}" * 64)[:64],
        "snapshot_hash": hashlib.sha256(snapshot_json.encode()).hexdigest(), "snapshot": snapshot_json,
        "amount": amount, "created": ORDER_AT.replace(tzinfo=None),
    })


def seed_journal(sequence, at=RECEIPT_AT):
    """Append a later synthetic receipt and a real two-line balanced legacy journal."""
    from src.database import db

    assert at.tzinfo is UTC and at >= ATTRIBUTION_AT
    order, receipt, journal = uid(100 + sequence), uid(200 + sequence), uid(300 + sequence)
    amount = db.session.execute(text("SELECT amount_minor FROM purchase_orders WHERE id=:id"), {"id": order}).scalar_one()
    values = {"order": order, "receipt": receipt, "journal": journal, "amount": amount,
              "at": at.replace(tzinfo=None), "event": f"synthetic_lifecycle_receipt_{sequence:04d}",
              "payload": (f"{sequence + 10:x}" * 64)[:64]}
    db.session.execute(text("""INSERT INTO payment_event_receipts
        (id,source,merchant_context,event_key,order_id,amount_minor,currency,payload_hash,created_at)
        VALUES (:receipt,'synthetic','isolated-tests',:event,:order,:amount,'USD',:payload,:at)"""), values)
    db.session.execute(text("""INSERT INTO settlement_journals
        (id,receipt_id,order_id,amount_minor,currency,created_at)
        VALUES (:journal,:receipt,:order,:amount,'USD',:at)"""), values)
    db.session.execute(text("""INSERT INTO settlement_entries
        (id,journal_id,line_number,account_code,side,amount_minor) VALUES
        (:debit,:journal,1,'provider_clearing','debit',:amount),
        (:credit,:journal,2,'unapplied_order_receipts','credit',:amount)"""),
        dict(values, debit=uid(400 + sequence * 2), credit=uid(401 + sequence * 2)))
    return journal


def policy(**changes):
    from src.services.affiliate_lifecycle_contract import AffiliatePolicy
    values = {"version": "TST_LIFECYCLE_1", "rate_basis_points": 1500,
              "basis": "paid_order_total", "currency": "USD", "hold_seconds": 3600,
              "minimum_payout_minor": 100, "rounding": "floor", "mode": "synthetic"}
    values.update(changes)
    return AffiliatePolicy(**values)


def svc():
    from src.services.affiliate_lifecycle_service import AffiliateLifecycleRehearsal
    return AffiliateLifecycleRehearsal


def error_type():
    from src.services.affiliate_lifecycle_contract import LifecycleError
    return LifecycleError


def refuse(call, code, status=409):
    with pytest.raises(error_type()) as raised:
        call()
    assert raised.value.code == code and raised.value.status == status and str(raised.value)
    return raised.value


def synthetic(result):
    assert result["mode"] == "synthetic"
    assert result["provider_verified"] is False
    assert result["payout_authorized"] is False


def counts():
    from src.database import db
    return db.session.execute(text("""SELECT
        (SELECT count(*) FROM affiliate_identity_evidence),
        (SELECT count(*) FROM affiliate_order_attributions),
        (SELECT count(*) FROM affiliate_commission_awards),
        (SELECT count(*) FROM affiliate_payout_commands)""")).one()


def legacy_digest():
    from src.database import db
    return db.session.execute(text("""SELECT
      md5(COALESCE((SELECT string_agg(to_jsonb(x)::text,'' ORDER BY x.id) FROM tenants x),'')),
      md5(COALESCE((SELECT string_agg(to_jsonb(x)::text,'' ORDER BY x.id) FROM users x),'')),
      md5(COALESCE((SELECT string_agg(to_jsonb(x)::text,'' ORDER BY x.id) FROM trading_programs x),'')),
      md5(COALESCE((SELECT string_agg(to_jsonb(x)::text,'' ORDER BY x.id) FROM purchase_orders x),'')),
      md5(COALESCE((SELECT string_agg(to_jsonb(x)::text,'' ORDER BY x.id) FROM payment_event_receipts x),'')),
      md5(COALESCE((SELECT string_agg(to_jsonb(x)::text,'' ORDER BY x.id) FROM settlement_journals x),'')),
      md5(COALESCE((SELECT string_agg(to_jsonb(x)::text,'' ORDER BY x.id) FROM settlement_entries x),''))""")).one()


def identity(user, subject, key, tenant=1, at=IDENTITY_AT):
    return svc().record_identity(user, tenant, subject, key, at=at)


def attribute(sequence, affiliate, buyer_evidence, affiliate_evidence, rules=None, at=ATTRIBUTION_AT):
    return svc().attribute_order(uid(100 + sequence), affiliate, buyer_evidence, affiliate_evidence,
                                 rules or policy(), at=at)


def evidence_pair(affiliate_user=3, buyer_subject=BUYER_HASH, affiliate_subject=AFFILIATE_HASH):
    return (identity(2, buyer_subject, "synthetic_buyer_evidence"),
            identity(affiliate_user, affiliate_subject, "synthetic_affiliate_evidence"))


def attributed(sequence=1, rules=None):
    buyer, affiliate = evidence_pair()
    return buyer, affiliate, attribute(sequence, 3, buyer["id"], affiliate["id"], rules)


def accrued(sequence=1, rules=None):
    buyer, affiliate, attribution = attributed(sequence, rules)
    journal = seed_journal(sequence)
    from src.database import db
    db.session.commit()  # real deferred ledger checks fire before affiliate accrual
    award = svc().accrue(attribution["id"], journal, at=ACCRUAL_AT)
    return buyer, affiliate, attribution, journal, award


def available(sequence=1):
    from src.database import db
    _buyer, _affiliate, attribution, journal, award = accrued(sequence)
    award = svc().release(award["id"], at=RELEASE_AT)
    db.session.commit()
    return attribution, journal, award


def prepare(award_id, approved_by=1, recipient=RECIPIENT_HASH, atomic=987_654_321, quote=QUOTE_HASH):
    return svc().prepare_payout(award_id, approved_by, "synthetic-local-network", "TST_LIFECYCLE_TOKEN",
                                recipient, atomic, quote, at=RELEASE_AT + timedelta(minutes=1))


def race(app, calls):
    """Exactly two independent Flask/SQLAlchemy sessions, shared barrier, bounded waits."""
    from src.database import db
    barrier = Barrier(2, timeout=10)
    def worker(call):
        with app.app_context():
            db.session.execute(text("SET statement_timeout='10s'"))
            barrier.wait()
            try:
                result = call()
                db.session.commit()
                return ("ok", result)
            except error_type() as exc:
                db.session.rollback()
                return ("refused", exc.code, exc.status)
            finally:
                db.session.remove()
    started = monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = [future.result(timeout=20) for future in [pool.submit(worker, call) for call in calls]]
    assert monotonic() - started < 20
    return result


def qident(value):
    return '"' + value.replace('"', '""') + '"'


def test_validation_not_found_and_disabled_or_nonisolated_gates(lifecycle_app, monkeypatch):
    from src.database import db
    with lifecycle_app.app_context():
        refuse(lambda: identity(2, BUYER_HASH, "synthetic_naive", at=IDENTITY_AT.replace(tzinfo=None)),
               "AFFILIATE_INVALID", 400)
        refuse(lambda: identity(2, "A" * 64, "synthetic_bad_hash"), "AFFILIATE_INVALID", 400)
        refuse(lambda: svc().accrue(uid(999), uid(998), at=ACCRUAL_AT), "AFFILIATE_NOT_FOUND", 404)
        assert counts() == (0, 0, 0, 0)
        db.session.rollback()

    def no_sql(*args, **kwargs):
        raise AssertionError("affiliate gate issued SQL")

    disabled = Flask("affiliate-disabled")
    disabled.config.update(TESTING=True, ISOLATED_STAGING_DATABASE=True,
                            AFFILIATE_LIFECYCLE_REHEARSAL_ENABLED=False)
    monkeypatch.setattr(db.session, "execute", no_sql)
    with disabled.app_context():
        refuse(lambda: identity(2, BUYER_HASH, "synthetic_disabled"), "AFFILIATE_NOT_CONFIGURED", 503)
    invalid_target = Flask("affiliate-nonisolated")
    invalid_target.config.update(TESTING=True, ISOLATED_STAGING_DATABASE=False,
                                 AFFILIATE_LIFECYCLE_REHEARSAL_ENABLED=True)
    with invalid_target.app_context():
        refuse(lambda: identity(2, BUYER_HASH, "synthetic_nonisolated"), "AFFILIATE_ISOLATION_REQUIRED", 503)


def test_identity_attribution_immutable_and_legacy_rows_preserved(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        buyer, affiliate = evidence_pair()
        attribution = attribute(1, 3, buyer["id"], affiliate["id"])
        assert attribution["created"] is True and len(attribution["policy_hash"]) == 64
        for result in (buyer, affiliate, attribution):
            synthetic(result)
        baseline = legacy_digest()
        db.session.commit()
        with pytest.raises(DBAPIError):
            db.session.execute(text("UPDATE affiliate_identity_evidence SET subject_hash=:v WHERE id=:id"),
                               {"v": OTHER_HASH, "id": buyer["id"]})
        db.session.rollback()
        with pytest.raises(DBAPIError):
            db.session.execute(text("UPDATE affiliate_order_attributions SET policy_hash=:v WHERE id=:id"),
                               {"v": OTHER_HASH, "id": attribution["id"]})
        db.session.rollback()
        assert legacy_digest() == baseline
        assert counts() == (2, 1, 0, 0)


def test_same_user_and_duplicate_subject_different_user_are_self_referrals(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        buyer = identity(2, BUYER_HASH, "synthetic_self_buyer")
        refuse(lambda: attribute(1, 2, buyer["id"], buyer["id"]), "AFFILIATE_SELF_REFERRAL")
        same_subject = identity(4, BUYER_HASH, "synthetic_same_subject")
        # The evidence records are allowed to preserve a same-person fingerprint;
        # only the commission attribution is ineligible.
        refuse(lambda: attribute(1, 4, buyer["id"], same_subject["id"]), "AFFILIATE_SELF_REFERRAL")
        assert counts() == (2, 0, 0, 0)
        db.session.rollback()


def test_foreign_and_changed_legacy_tenant_refuse_before_award(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        buyer = identity(2, BUYER_HASH, "synthetic_scope_buyer")
        foreign = identity(5, AFFILIATE_HASH, "synthetic_foreign_affiliate", tenant=2)
        refuse(lambda: attribute(1, 5, buyer["id"], foreign["id"]), "AFFILIATE_SCOPE_MISMATCH")
        db.session.rollback()

        _buyer, _affiliate, attribution = attributed(2)
        journal = seed_journal(2)
        db.session.commit()
        # Synthetic legacy drift after quote/attribution must be rechecked at accrual.
        db.session.execute(text("UPDATE users SET tenant_id=2 WHERE id=3"))
        db.session.commit()
        refuse(lambda: svc().accrue(attribution["id"], journal, at=ACCRUAL_AT), "AFFILIATE_SCOPE_MISMATCH")
        db.session.rollback()
        assert counts() == (2, 1, 0, 0)


def test_attribution_precedes_receipt_and_policy_replay_never_rewrites(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        buyer, affiliate = evidence_pair()
        seed_journal(1)
        db.session.commit()
        refuse(lambda: attribute(1, 3, buyer["id"], affiliate["id"]), "AFFILIATE_STATE_CONFLICT")
        db.session.rollback()
        first = attribute(2, 3, buyer["id"], affiliate["id"])
        replay = attribute(2, 3, buyer["id"], affiliate["id"])
        assert first["created"] is True and replay["created"] is False
        assert first["id"] == replay["id"] and first["policy_hash"] == replay["policy_hash"]
        db.session.commit()
        refuse(lambda: attribute(2, 3, buyer["id"], affiliate["id"], policy(rate_basis_points=1600)),
               "AFFILIATE_CONFLICT")
        db.session.rollback()
        assert counts() == (2, 1, 0, 0)


def test_accrual_is_exact_floor_and_one_award_for_one_balanced_journal(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        _buyer, _affiliate, attribution, journal, award = accrued(1)
        replay = svc().accrue(attribution["id"], journal, at=ACCRUAL_AT)
        # 1001 * 1500 // 10000: exact integer floor, never float money.
        assert award["created"] is True and replay["created"] is False
        assert award["id"] == replay["id"] and award["amount_minor"] == replay["amount_minor"] == 150
        synthetic(award)
        row = db.session.execute(text("""SELECT a.amount_minor,a.state,a.review_open,a.release_at,
            j.amount_minor,r.created_at FROM affiliate_commission_awards a
            JOIN settlement_journals j ON j.id=a.journal_id
            JOIN payment_event_receipts r ON r.id=j.receipt_id WHERE a.id=:id"""),
            {"id": award["id"]}).one()
        assert row == (150, "held", False, RELEASE_AT, 1001, RECEIPT_AT.replace(tzinfo=None))
        assert counts() == (2, 1, 1, 0)
        db.session.commit()


def test_zero_floor_award_refuses_with_no_partial_award(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        _buyer, _affiliate, attribution = attributed(5)
        journal = seed_journal(5)
        db.session.commit()
        refuse(lambda: svc().accrue(attribution["id"], journal, at=ACCRUAL_AT), "AFFILIATE_ZERO_AWARD")
        db.session.rollback()
        assert counts() == (2, 1, 0, 0)


def test_attribution_and_award_races_have_one_durable_winner_and_bounded_time(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        buyer, affiliate = evidence_pair()
        db.session.commit()
    attribution_results = race(lifecycle_app, [
        lambda: attribute(3, 3, buyer["id"], affiliate["id"]),
        lambda: attribute(3, 3, buyer["id"], affiliate["id"]),
    ])
    assert [item[0] for item in attribution_results] == ["ok", "ok"]
    attributions = [item[1] for item in attribution_results]
    assert sorted(item["created"] for item in attributions) == [False, True]
    assert len({item["id"] for item in attributions}) == 1
    attribution = attributions[0]
    with lifecycle_app.app_context():
        journal = seed_journal(3)
        db.session.commit()
    award_results = race(lifecycle_app, [
        lambda: svc().accrue(attribution["id"], journal, at=ACCRUAL_AT),
        lambda: svc().accrue(attribution["id"], journal, at=ACCRUAL_AT),
    ])
    assert [item[0] for item in award_results] == ["ok", "ok"]
    awards = [item[1] for item in award_results]
    assert sorted(item["created"] for item in awards) == [False, True]
    assert len({item["id"] for item in awards}) == 1
    with lifecycle_app.app_context():
        assert counts() == (2, 1, 1, 0)
        db.session.rollback()


def test_maturity_review_and_reverse_use_only_allowed_transitions(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        _buyer, _affiliate, _attribution, _journal, award = accrued(1)
        db.session.commit()
        refuse(lambda: svc().release(award["id"], at=RELEASE_AT - timedelta(microseconds=1)),
               "AFFILIATE_STATE_CONFLICT")
        reviewed = svc().review(award["id"], True, at=ACCRUAL_AT + timedelta(minutes=1))
        assert reviewed["state"] == "held" and reviewed["review_open"] is True
        db.session.commit()
        refuse(lambda: svc().release(award["id"], at=RELEASE_AT), "AFFILIATE_STATE_CONFLICT")
        cleared = svc().review(award["id"], False, at=RELEASE_AT)
        assert cleared["review_open"] is False
        db.session.commit()
        released = svc().release(award["id"], at=RELEASE_AT + timedelta(microseconds=1))
        assert released["state"] == "available"
        reversed_award = svc().reverse(award["id"], "synthetic_reverse_evidence_1",
                                       at=RELEASE_AT + timedelta(seconds=1))
        assert reversed_award["state"] == "reversed"
        assert reversed_award["reversal_event_key"] == "synthetic_reverse_evidence_1"
        synthetic(reversed_award)
        refuse(lambda: svc().release(award["id"], at=RELEASE_AT + timedelta(seconds=2)),
               "AFFILIATE_STATE_CONFLICT")
        db.session.rollback()


def test_prepare_root_minimum_atomic_token_and_reserve_are_one_unit(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        _attribution, _journal, award = available(1)
        refuse(lambda: prepare(award["id"], approved_by=2), "AFFILIATE_ROOT_REQUIRED", 403)
        db.session.rollback()
        command = prepare(award["id"], atomic=987_654_321)
        assert command["state"] == "planned"
        synthetic(command)
        row = db.session.execute(text("""SELECT c.network_id,c.asset_id,c.recipient_hash,c.amount_atomic,
            c.quote_hash,c.state,c.attempt_token,c.transfer_key,a.state,a.review_open
            FROM affiliate_payout_commands c JOIN affiliate_commission_awards a ON a.id=c.award_id
            WHERE c.id=:id"""), {"id": command["id"]}).one()
        assert row == ("synthetic-local-network", "TST_LIFECYCLE_TOKEN", RECIPIENT_HASH, 987_654_321,
                       QUOTE_HASH, "planned", None, None, "reserved", False)
        # Explicit opaque atomic units: this asserts neither USD=USDT nor a real transfer.
        assert row[3] != award["amount_minor"]
        refuse(lambda: svc().reverse(award["id"], "synthetic_after_reserve",
                                     at=RELEASE_AT + timedelta(minutes=2)), "AFFILIATE_STATE_CONFLICT")
        db.session.rollback()


def test_double_claim_one_token_uncertain_no_reclaim_wrong_token_then_terminal_confirm(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        _attribution, _journal, award = available(1)
        command = prepare(award["id"])
        db.session.commit()
    claimed = race(lifecycle_app, [
        lambda: svc().claim_payout(command["id"], at=RELEASE_AT + timedelta(minutes=2)),
        lambda: svc().claim_payout(command["id"], at=RELEASE_AT + timedelta(minutes=2)),
    ])
    winners = [item[1] for item in claimed if item[0] == "ok"]
    assert len(winners) == 1 and winners[0]["state"] == "dispatched"
    token = winners[0]["attempt_token"]
    assert isinstance(token, str) and token
    assert ("refused", "AFFILIATE_STATE_CONFLICT", 409) in claimed
    with lifecycle_app.app_context():
        uncertain = svc().mark_uncertain(command["id"], token, at=RELEASE_AT + timedelta(minutes=3))
        assert uncertain["state"] == "uncertain" and uncertain["attempt_token"] == token
        refuse(lambda: svc().claim_payout(command["id"], at=RELEASE_AT + timedelta(minutes=4)),
               "AFFILIATE_STATE_CONFLICT")
        refuse(lambda: svc().confirm_payout(command["id"], uid(998), "synthetic_wrong_token",
                                            at=RELEASE_AT + timedelta(minutes=4)), "AFFILIATE_STATE_CONFLICT")
        confirmed = svc().confirm_payout(command["id"], token, "synthetic_terminal_transfer_1",
                                         at=RELEASE_AT + timedelta(minutes=5))
        assert confirmed["state"] == "confirmed" and confirmed["attempt_token"] == token
        synthetic(confirmed)
        assert db.session.execute(text("SELECT state FROM affiliate_commission_awards WHERE id=:id"),
                                  {"id": award["id"]}).scalar_one() == "paid"
        # A confirmed command is terminal; it cannot be re-opened as uncertain.
        refuse(lambda: svc().mark_uncertain(command["id"], token, at=RELEASE_AT + timedelta(minutes=6)),
               "AFFILIATE_STATE_CONFLICT")
        db.session.rollback()


def test_shared_transfer_key_is_unique_and_second_award_stays_reserved(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        _attribution1, _journal1, award1 = available(1)
        buyer = db.session.execute(text("SELECT id FROM affiliate_identity_evidence WHERE user_id=2")).scalar_one()
        affiliate = db.session.execute(text("SELECT id FROM affiliate_identity_evidence WHERE user_id=3")).scalar_one()
        attribution2 = attribute(2, 3, buyer, affiliate)
        journal2 = seed_journal(2)
        db.session.commit()
        award2 = svc().accrue(attribution2["id"], journal2, at=ACCRUAL_AT)
        award2 = svc().release(award2["id"], at=RELEASE_AT)
        command1, command2 = prepare(award1["id"]), prepare(award2["id"], recipient=OTHER_HASH)
        claim1 = svc().claim_payout(command1["id"], at=RELEASE_AT + timedelta(minutes=2))
        claim2 = svc().claim_payout(command2["id"], at=RELEASE_AT + timedelta(minutes=2))
        first = svc().confirm_payout(command1["id"], claim1["attempt_token"], "synthetic_shared_transfer",
                                     at=RELEASE_AT + timedelta(minutes=3))
        assert first["state"] == "confirmed"
        db.session.commit()
        refuse(lambda: svc().confirm_payout(command2["id"], claim2["attempt_token"], "synthetic_shared_transfer",
                                             at=RELEASE_AT + timedelta(minutes=3)), "AFFILIATE_CONFLICT")
        assert db.session.execute(text("SELECT state FROM affiliate_commission_awards WHERE id=:id"),
                                  {"id": award2["id"]}).scalar_one() == "reserved"
        db.session.rollback()


def test_savepoints_remove_post_insert_and_post_update_even_when_caller_commits(lifecycle_app):
    """The event raises after PostgreSQL accepted DML, proving the nested rollback."""
    from src.database import db
    with lifecycle_app.app_context():
        seen_insert = []
        def fail_after_insert(conn, cursor, statement, parameters, context, executemany):
            rendered = " ".join(statement.lower().split())
            if rendered.startswith("insert into public.affiliate_identity_evidence"):
                seen_insert.append(statement)
                raise RuntimeError("after actual affiliate identity INSERT")
        event.listen(db.engine, "after_cursor_execute", fail_after_insert)
        try:
            with pytest.raises(RuntimeError, match="actual affiliate identity INSERT"):
                identity(2, BUYER_HASH, "synthetic_post_insert_failure")
        finally:
            event.remove(db.engine, "after_cursor_execute", fail_after_insert)
        assert seen_insert
        db.session.commit()
        assert counts() == (0, 0, 0, 0)

        _buyer, _affiliate, _attribution, _journal, award = accrued(1)
        db.session.commit()
        seen_update = []
        def fail_after_update(conn, cursor, statement, parameters, context, executemany):
            rendered = " ".join(statement.lower().replace('"', '').split())
            if rendered.startswith("update public.affiliate_commission_awards"):
                seen_update.append(statement)
                raise RuntimeError("after actual affiliate award UPDATE")
        event.listen(db.engine, "after_cursor_execute", fail_after_update)
        try:
            with pytest.raises(RuntimeError, match="actual affiliate award UPDATE"):
                svc().review(award["id"], True, at=ACCRUAL_AT + timedelta(minutes=1))
        finally:
            event.remove(db.engine, "after_cursor_execute", fail_after_update)
        assert seen_update
        db.session.commit()
        assert db.session.execute(text("SELECT state,review_open FROM affiliate_commission_awards WHERE id=:id"),
                                  {"id": award["id"]}).one() == ("held", False)


def test_direct_sql_cannot_bypass_immutability_or_award_command_state(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        buyer, _affiliate, attribution, _journal, award = accrued(1)
        award = svc().release(award["id"], at=RELEASE_AT)
        command = prepare(award["id"])
        db.session.commit()
        attempted = [
            ("UPDATE affiliate_identity_evidence SET event_key='direct_mutation' WHERE id=:id", buyer["id"]),
            ("UPDATE affiliate_order_attributions SET affiliate_user_id=2 WHERE id=:id", attribution["id"]),
            ("UPDATE affiliate_commission_awards SET state='paid' WHERE id=:id", award["id"]),
            ("UPDATE affiliate_payout_commands SET state='confirmed' WHERE id=:id", command["id"]),
            ("DELETE FROM affiliate_commission_awards WHERE id=:id", award["id"]),
        ]
        for statement, identifier in attempted:
            with pytest.raises(DBAPIError):
                db.session.execute(text(statement), {"id": identifier})
            db.session.rollback()
        assert db.session.execute(text("SELECT state,review_open FROM affiliate_commission_awards WHERE id=:id"),
                                  {"id": award["id"]}).one() == ("reserved", False)
        assert db.session.execute(text("SELECT state,attempt_token,transfer_key FROM affiliate_payout_commands WHERE id=:id"),
                                  {"id": command["id"]}).one() == ("planned", None, None)


@pytest.mark.parametrize("tamper", ["head", "trigger", "function", "replica"])
def test_storage_gate_refuses_tampered_head_trigger_function_or_replication(lifecycle_app, tamper):
    from src.database import db
    with lifecycle_app.app_context():
        if tamper == "head":
            db.session.execute(text("UPDATE alembic_version SET version_num='20261011_000008'"))
            db.session.commit()
        elif tamper in ("trigger", "function"):
            row = db.session.execute(text("""SELECT t.tgname,p.proname FROM pg_trigger t
                JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace pn ON pn.oid=p.pronamespace
                WHERE n.nspname='public' AND pn.nspname='public'
                  AND c.relname='affiliate_identity_evidence' AND NOT t.tgisinternal
                ORDER BY t.tgname LIMIT 1""")).one()
            if tamper == "trigger":
                db.session.execute(text("ALTER TABLE public.affiliate_identity_evidence DISABLE TRIGGER " + qident(row[0])))
            else:
                db.session.execute(text("CREATE OR REPLACE FUNCTION public." + qident(row[1]) + "() "
                                        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$"))
            db.session.commit()
        else:
            db.session.execute(text("SET LOCAL session_replication_role=replica"))
        refuse(lambda: identity(2, BUYER_HASH, "synthetic_storage_canary"),
               "AFFILIATE_STORAGE_NOT_READY", 503)
        db.session.rollback()
        assert counts() == (0, 0, 0, 0)


def test_savepoints_remove_all_post_dml_lifecycle_units_when_outer_caller_commits(lifecycle_app):
    """Raise after accepted PostgreSQL DML; each service savepoint must remove all parts."""
    from src.database import db

    def fail_after(prefix, action, label):
        seen = []
        def hook(conn, cursor, statement, parameters, context, executemany):
            rendered = " ".join(statement.lower().replace('"', '').split())
            if rendered.startswith(prefix):
                seen.append(statement)
                raise RuntimeError("after actual " + label)
        event.listen(db.engine, "after_cursor_execute", hook)
        try:
            with pytest.raises(RuntimeError, match=label):
                action()
        finally:
            event.remove(db.engine, "after_cursor_execute", hook)
        assert seen
        db.session.commit()  # prove savepoint cleanup even when caller commits

    with lifecycle_app.app_context():
        buyer, affiliate = evidence_pair()
        db.session.commit()
        fail_after("insert into public.affiliate_order_attributions",
                   lambda: attribute(1, 3, buyer["id"], affiliate["id"]),
                   "affiliate attribution INSERT")
        assert counts() == (2, 0, 0, 0)

        attribution = attribute(1, 3, buyer["id"], affiliate["id"])
        db.session.commit()
        journal = seed_journal(1)
        db.session.commit()
        fail_after("insert into public.affiliate_commission_awards",
                   lambda: svc().accrue(attribution["id"], journal, at=ACCRUAL_AT),
                   "affiliate award INSERT")
        assert counts() == (2, 1, 0, 0)

        award1 = svc().accrue(attribution["id"], journal, at=ACCRUAL_AT)
        award1 = svc().release(award1["id"], at=RELEASE_AT)
        db.session.commit()
        fail_after("insert into public.affiliate_payout_commands",
                   lambda: prepare(award1["id"]), "affiliate payout INSERT")
        assert db.session.execute(text("SELECT state FROM affiliate_commission_awards WHERE id=:id"),
                                  {"id": award1["id"]}).scalar_one() == "available"
        assert counts() == (2, 1, 1, 0)

        # Second award isolates the post-reserve UPDATE failure from the first payout.
        attribution2 = attribute(2, 3, buyer["id"], affiliate["id"])
        db.session.commit()
        journal2 = seed_journal(2)
        db.session.commit()
        award2 = svc().accrue(attribution2["id"], journal2, at=ACCRUAL_AT)
        award2 = svc().release(award2["id"], at=RELEASE_AT)
        db.session.commit()
        fail_after("update public.affiliate_commission_awards set state='reserved'",
                   lambda: prepare(award2["id"]), "affiliate reserve UPDATE")
        assert db.session.execute(text("SELECT state FROM affiliate_commission_awards WHERE id=:id"),
                                  {"id": award2["id"]}).scalar_one() == "available"
        assert db.session.execute(text("SELECT count(*) FROM affiliate_payout_commands WHERE award_id=:id"),
                                  {"id": award2["id"]}).scalar_one() == 0

        command1 = prepare(award1["id"])
        db.session.commit()
        claim1 = svc().claim_payout(command1["id"], at=RELEASE_AT + timedelta(minutes=2))
        db.session.commit()
        fail_after("update public.affiliate_payout_commands set state='confirmed'",
                   lambda: svc().confirm_payout(command1["id"], claim1["attempt_token"], "synthetic_savepoint_confirm_1",
                                                 at=RELEASE_AT + timedelta(minutes=3)),
                   "affiliate confirmed-command UPDATE")
        assert db.session.execute(text("SELECT state FROM affiliate_payout_commands WHERE id=:id"),
                                  {"id": command1["id"]}).scalar_one() == "dispatched"
        assert db.session.execute(text("SELECT state FROM affiliate_commission_awards WHERE id=:id"),
                                  {"id": award1["id"]}).scalar_one() == "reserved"

        command2 = prepare(award2["id"])
        db.session.commit()
        claim2 = svc().claim_payout(command2["id"], at=RELEASE_AT + timedelta(minutes=2))
        db.session.commit()
        fail_after("update public.affiliate_commission_awards set state='paid'",
                   lambda: svc().confirm_payout(command2["id"], claim2["attempt_token"], "synthetic_savepoint_confirm_2",
                                                 at=RELEASE_AT + timedelta(minutes=3)),
                   "affiliate paid-award UPDATE")
        assert db.session.execute(text("SELECT state FROM affiliate_payout_commands WHERE id=:id"),
                                  {"id": command2["id"]}).scalar_one() == "dispatched"
        assert db.session.execute(text("SELECT state FROM affiliate_commission_awards WHERE id=:id"),
                                  {"id": award2["id"]}).scalar_one() == "reserved"


def test_prepare_race_same_award_has_one_command_and_one_exact_replay(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        _attribution, _journal, award = available(1)
    results = race(lifecycle_app, [
        lambda: prepare(award["id"]),
        lambda: prepare(award["id"]),
    ])
    assert [item[0] for item in results] == ["ok", "ok"]
    commands = [item[1] for item in results]
    assert sorted(item["created"] for item in commands) == [False, True]
    assert len({item["id"] for item in commands}) == 1
    with lifecycle_app.app_context():
        assert counts() == (2, 1, 1, 1)
        assert db.session.execute(text("SELECT state FROM affiliate_commission_awards WHERE id=:id"),
                                  {"id": award["id"]}).scalar_one() == "reserved"
        db.session.rollback()


def test_direct_sql_half_confirm_is_rejected_by_deferred_award_command_consistency(lifecycle_app):
    from src.database import db
    with lifecycle_app.app_context():
        _attribution, _journal, award = available(1)
        command = prepare(award["id"])
        db.session.commit()
        claim = svc().claim_payout(command["id"], at=RELEASE_AT + timedelta(minutes=2))
        db.session.commit()
        # This direct write has a valid token/transfer shape and command transition,
        # but omits the paired reserved->paid award update.  The real deferred trigger
        # must refuse commit rather than permit a half-confirmed payout state.
        db.session.execute(text("""UPDATE affiliate_payout_commands
            SET state='confirmed',transfer_key='synthetic_half_confirm',updated_at=:at WHERE id=:id"""),
            {"id": command["id"], "at": RELEASE_AT + timedelta(minutes=3)})
        with pytest.raises(DBAPIError):
            db.session.commit()
        db.session.rollback()
        assert db.session.execute(text("SELECT state,attempt_token,transfer_key FROM affiliate_payout_commands WHERE id=:id"),
                                  {"id": command["id"]}).one() == ("dispatched", claim["attempt_token"], None)
        assert db.session.execute(text("SELECT state FROM affiliate_commission_awards WHERE id=:id"),
                                  {"id": award["id"]}).scalar_one() == "reserved"


@pytest.mark.parametrize("change", [
    "UPDATE users SET is_active=false WHERE id=1",
    "UPDATE users SET tenant_id=2 WHERE id=1",
], ids=["inactive-root", "cross-tenant-root"])
def test_root_capability_drift_blocks_claim_without_command_or_award_transition(lifecycle_app, change):
    from src.database import db
    with lifecycle_app.app_context():
        _attribution, _journal, award = available(1)
        command = prepare(award["id"])
        db.session.commit()
        db.session.execute(text(change))
        db.session.commit()
        refuse(lambda: svc().claim_payout(command["id"], at=RELEASE_AT + timedelta(minutes=2)),
               "AFFILIATE_ROOT_REQUIRED", 403)
        assert db.session.execute(text("SELECT state,attempt_token FROM affiliate_payout_commands WHERE id=:id"),
                                  {"id": command["id"]}).one() == ("planned", None)
        assert db.session.execute(text("SELECT state FROM affiliate_commission_awards WHERE id=:id"),
                                  {"id": award["id"]}).scalar_one() == "reserved"
        db.session.rollback()


def test_service_owns_timeout_budget_and_contains_lock_timeout(lifecycle_app):
    """No injected service timeout: held order triggers the service's own 3 s limit."""
    from src.database import db
    with lifecycle_app.app_context():
        buyer, affiliate = evidence_pair()
        db.session.commit()
        engine = db.engine
    with engine.connect() as blocker:
        transaction = blocker.begin()
        blocker.execute(text('SELECT id FROM purchase_orders WHERE id=:id FOR UPDATE'), {'id': uid(101)})
        try:
            with lifecycle_app.app_context():
                svc()._prepare(ATTRIBUTION_AT)
                assert db.session.execute(text('SHOW lock_timeout')).scalar_one() == '3s'
                assert db.session.execute(text('SHOW statement_timeout')).scalar_one() == '5s'
                started = monotonic()
                refuse(lambda: attribute(1, 3, buyer['id'], affiliate['id']), 'AFFILIATE_CONFLICT')
                assert 2 <= monotonic() - started < 8
                # A lock-timeout refusal cleaned its savepoint; caller can commit
                # without an aborted outer session or partial attribution.
                db.session.commit()
                assert counts() == (2, 0, 0, 0)
        finally:
            transaction.rollback()


def test_storage_readiness_against_real_head(lifecycle_app):
    from src.services.affiliate_lifecycle_storage import require_storage_ready
    with lifecycle_app.app_context():
        require_storage_ready()
