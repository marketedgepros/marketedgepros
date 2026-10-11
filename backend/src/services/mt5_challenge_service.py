"""MT5 challenge integration boundary, not an active provisioning adapter.

Legacy callers retain their async/sync interface but cannot create an account,
change balances/statuses or expose trading credentials from mutable paid flags.
No database/provider/secret access occurs before refusal. Explicit provider
identity, immutable paid entitlement and durable commands are still required.
"""
from src.services.mt5_service import MT5ProviderNotConfigured


class MT5ChallengeService:
    @staticmethod
    async def create_mt5_account_for_challenge(challenge_id):
        raise MT5ProviderNotConfigured()

    @staticmethod
    def _get_account_parameters(program, challenge):
        # Never guess group/leverage/funding from a mutable catalog or fallback.
        raise MT5ProviderNotConfigured()

    @staticmethod
    async def disable_mt5_account_for_challenge(challenge_id, reason='Challenge ended'):
        raise MT5ProviderNotConfigured()

    @staticmethod
    async def update_challenge_from_mt5(challenge_id):
        raise MT5ProviderNotConfigured()

    @staticmethod
    def get_mt5_credentials(challenge_id, user_id):
        raise MT5ProviderNotConfigured()


mt5_challenge_service = MT5ChallengeService()
