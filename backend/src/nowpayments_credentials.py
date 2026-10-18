"""Pure local validation for NOWPayments API credentials.

This validates only a bounded, transport-safe credential shape. It does not make
provider-authentication claims; the provider remains authoritative for that.
"""

MINIMUM_NOWPAYMENTS_API_KEY_LENGTH = 16
MAXIMUM_NOWPAYMENTS_API_KEY_LENGTH = 512
_KNOWN_WEAK_CREDENTIALS = frozenset({
    "change-me",
    "secret",
    "default",
    "placeholder",
})
_PLACEHOLDER_MARKERS = ("placeholder", "example", "replace", "your_", "your-")


def is_valid_nowpayments_api_key(value):
    """Accept a printable, non-placeholder NOWPayments API credential.

    API credentials are provider-issued identifiers rather than generated local
    signing secrets, so their valid length range is intentionally independent
    from the minimum used for HMAC, JWT, and runtime signing secrets.
    """
    if (
        not isinstance(value, str)
        or not MINIMUM_NOWPAYMENTS_API_KEY_LENGTH <= len(value) <= MAXIMUM_NOWPAYMENTS_API_KEY_LENGTH
        or not value.isascii()
    ):
        return False
    lowered = value.lower()
    return (
        value not in _KNOWN_WEAK_CREDENTIALS
        and not any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
        and lowered not in _KNOWN_WEAK_CREDENTIALS
        and not any(marker in lowered for marker in _PLACEHOLDER_MARKERS)
        and len(set(value)) >= 8
    )
