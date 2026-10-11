"""Inert MT5 stream interface pending an authenticated provider event protocol.

No default ws:// server, reconnect loop, unbounded message stream, database
update or Socket.IO emission is activated. Event identity/order/ownership and
source verification must be implemented before enabling stream ingestion.
"""
from src.services.mt5_service import MT5ProviderNotConfigured


class MT5WebSocketService:
    def __init__(self, db_session, socketio_instance):
        # Do not retain/use supplied transports or inspect an external session.
        self.running = False

    async def start(self):
        raise MT5ProviderNotConfigured()

    async def stop(self):
        self.running = False

    async def connect_deal_stream(self):
        raise MT5ProviderNotConfigured()

    async def connect_account_stream(self):
        raise MT5ProviderNotConfigured()

    async def connect_position_stream(self):
        raise MT5ProviderNotConfigured()

    async def handle_deal_update(self, message):
        raise MT5ProviderNotConfigured()

    async def handle_account_update(self, message):
        raise MT5ProviderNotConfigured()

    async def handle_position_update(self, message):
        raise MT5ProviderNotConfigured()

    async def calculate_challenge_progress(self, challenge_id):
        raise MT5ProviderNotConfigured()


mt5_websocket_service = None


def init_mt5_websocket_service(db_session, socketio_instance):
    # Retain an inert instance for imports; this does not connect or start work.
    global mt5_websocket_service
    mt5_websocket_service = MT5WebSocketService(db_session, socketio_instance)
    return mt5_websocket_service
