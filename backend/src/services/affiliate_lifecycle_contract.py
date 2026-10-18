"""Typed synthetic affiliate contract; no product defaults or provider authority."""
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import hashlib
import json
import re


class LifecycleError(ValueError):
    def __init__(self, message, code='AFFILIATE_INVALID', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def fail(message, code='AFFILIATE_CONFLICT', status=409):
    raise LifecycleError(message, code, status)


def exact_int(value, low, high, name='integer'):
    if type(value) is not int or not low <= value <= high:
        fail('A bounded exact ' + name + ' is required', 'AFFILIATE_INVALID', 400)
    return value


def exact_text(value, pattern, length, name='identity'):
    if type(value) is not str or not 1 <= len(value) <= length or re.fullmatch(pattern, value, re.ASCII) is None:
        fail('A bounded exact ' + name + ' is required', 'AFFILIATE_INVALID', 400)
    return value


def identifier(value, length=128):
    return exact_text(value, r'[A-Za-z0-9_.:-]+', length)


def uuid(value):
    return exact_text(value, r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 36)


def digest_text(value):
    return exact_text(value, r'[0-9a-f]{64}', 64, 'fingerprint')


def utc_datetime(value):
    if type(value) is not datetime or value.tzinfo is not timezone.utc or value.fold != 0:
        fail('An exact UTC timestamp is required', 'AFFILIATE_INVALID', 400)
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('ascii')).hexdigest()


@dataclass(frozen=True)
class AffiliatePolicy:
    version: str
    rate_basis_points: int
    basis: str
    currency: str
    hold_seconds: int
    minimum_payout_minor: int
    rounding: str
    mode: str

    def __post_init__(self):
        identifier(self.version, 64)
        exact_int(self.rate_basis_points, 1, 10000, 'rate in basis points')
        exact_int(self.hold_seconds, 0, 31536000, 'hold in seconds')
        exact_int(self.minimum_payout_minor, 1, 9999999999, 'minimum minor units')
        for name, expected in [('basis', 'paid_order_total'), ('currency', 'USD'),
                               ('rounding', 'floor'), ('mode', 'synthetic')]:
            if type(getattr(self, name)) is not str or getattr(self, name) != expected:
                fail('Only the explicit synthetic paid-order-total USD policy is represented', 'AFFILIATE_INVALID', 400)

    def canonical_dict(self):
        self.__post_init__()
        return asdict(self)

    @property
    def digest(self):
        return digest(self.canonical_dict())

    def commission_minor(self, paid_minor):
        self.__post_init__()
        exact_int(paid_minor, 1, 9999999999, 'paid minor units')
        result = paid_minor * self.rate_basis_points // 10000
        if not result:
            fail('The exact commission rounds to zero', 'AFFILIATE_ZERO_AWARD', 409)
        return result


def decode_policy(value, fingerprint):
    expected = {field.name for field in fields(AffiliatePolicy)}
    if type(value) is not dict or len(value) != len(expected) or any(type(key) is not str for key in value) or set(value) != expected:
        fail('Stored policy shape differs from contract', 'AFFILIATE_STORAGE_NOT_READY', 503)
    try:
        policy = AffiliatePolicy(**value)
        if policy.digest != fingerprint:
            raise ValueError('Fingerprint mismatch')
        return policy
    except (ValueError, TypeError):
        fail('Stored policy is inconsistent', 'AFFILIATE_STORAGE_NOT_READY', 503)
