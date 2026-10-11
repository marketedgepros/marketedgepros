"""Unconfigured MT5 provider boundary; no implicit credentials or network work.

The previous adapter assumed an undocumented remote API, plaintext HTTP/default
credentials and retries for account creation/balance changes. Those operations
cannot safely run until explicit provider contract, isolated test configuration,
source-bound entitlement and idempotent command protocol are implemented.
"""


class MT5APIError(Exception):
    """Base MT5 provider error retained for existing callers."""


class MT5AuthenticationError(MT5APIError):
    pass


class MT5AccountNotFoundError(MT5APIError):
    pass


class MT5RateLimitError(MT5APIError):
    pass


class MT5ProviderNotConfigured(MT5APIError):
    code = 'MT5_PROVIDER_NOT_CONFIGURED'
    status = 503

    def __init__(self):
        super().__init__('Verified MT5 provider integration is not configured')


class MT5Service:
    """Inert legacy interface, not a mock/demo or configurable live adapter.

    Constructing/importing this class neither reads credentials nor opens a
    network session. Flags or legacy environment values cannot activate it.
    Unknown outcome of a provisioning command must be reconciled by future
    provider identity, never blindly retried or replaced with a random login.
    """

    def authenticate(self):
        raise MT5ProviderNotConfigured()

    def create_account(self, *args, **kwargs):
        raise MT5ProviderNotConfigured()

    def get_account_info(self, *args, **kwargs):
        raise MT5ProviderNotConfigured()

    def get_positions(self, *args, **kwargs):
        raise MT5ProviderNotConfigured()

    def get_trade_history(self, *args, **kwargs):
        raise MT5ProviderNotConfigured()

    def update_balance(self, *args, **kwargs):
        raise MT5ProviderNotConfigured()

    def disable_account(self, *args, **kwargs):
        raise MT5ProviderNotConfigured()

    def disable_trading(self, *args, **kwargs):
        raise MT5ProviderNotConfigured()


mt5_service = MT5Service()
