"""
Integration Tests for MT5 Routes
Professional tests following MarketEdgePros patterns
"""
import pytest
import uuid
from src.database import db


def extract_cookie_value(response, cookie_name):
    """Helper to extract cookie value from response"""
    cookies = response.headers.getlist('Set-Cookie')
    for cookie in cookies:
        if cookie.startswith(f'{cookie_name}='):
            token_part = cookie.split(';')[0]
            return token_part.split('=', 1)[1]
    return None


class TestMT5AccountsAuth:
    """Test MT5 accounts endpoint authentication"""
    
    def test_get_accounts_requires_auth(self, client):
        """Test that getting accounts requires authentication"""
        response = client.get('/api/mt5/accounts')
        assert response.status_code == 401
    
    def test_get_account_details_requires_auth(self, client):
        """Test that getting account details requires authentication"""
        response = client.get('/api/mt5/accounts/1')
        assert response.status_code == 401
    
    def test_create_account_requires_auth(self, client):
        """Test that creating account requires authentication"""
        response = client.post('/api/mt5/accounts/create', json={
            'challenge_id': 1
        })
        assert response.status_code == 401
    
    def test_get_trades_requires_auth(self, client):
        """Test that getting trades requires authentication"""
        response = client.get('/api/mt5/accounts/1/trades')
        assert response.status_code == 401
    
    def test_get_positions_requires_auth(self, client):
        """Test that getting positions requires authentication"""
        response = client.get('/api/mt5/accounts/1/positions')
        assert response.status_code == 401
    
    def test_get_stats_requires_auth(self, client):
        """Test that getting stats requires authentication"""
        response = client.get('/api/mt5/accounts/1/stats')
        assert response.status_code == 401
    
    def test_sync_account_requires_auth(self, client):
        """Test that syncing account requires authentication"""
        response = client.post('/api/mt5/sync/1')
        assert response.status_code == 401


class TestMT5AccountsEndpoint:
    """Test MT5 accounts listing endpoint"""
    
    def test_get_accounts_empty(self, client, session):
        """Test getting accounts when user has none"""
        from src.models.user import User
        
        # Create trader
        email = f'trader_{uuid.uuid4().hex[:8]}@test.com'
        user = User(email=email, first_name='Test', last_name='Trader', role='trader')
        user.set_password('Test123!')
        user.is_verified = True
        session.add(user)
        session.commit()
        
        # Login
        response = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': 'Test123!'
        })
        assert response.status_code == 200
        
        # Get accounts
        response = client.get('/api/mt5/accounts')
        
        assert response.status_code == 200
        data = response.json
        assert data['success'] is True
        assert 'accounts' in data
        assert len(data['accounts']) == 0
    
    def test_get_accounts_with_one_account(self, client, session):
        """Test getting accounts when user has one account"""
        from src.models.user import User
        from src.models.mt5_models import MT5Account
        
        # Create trader
        email = f'trader_{uuid.uuid4().hex[:8]}@test.com'
        user = User(email=email, first_name='Test', last_name='Trader', role='trader')
        user.set_password('Test123!')
        user.is_verified = True
        session.add(user)
        session.commit()
        
        # Create MT5 account
        mt5_account = MT5Account(
            user_id=user.id,
            mt5_login='12345',
            mt5_password_encrypted='encrypted_password',
            mt5_group='demo\\\\forex',
            mt5_server='Demo-Server',
            balance=10000.0,
            equity=10000.0,
            status='active'
        )
        session.add(mt5_account)
        session.commit()
        
        # Login
        response = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': 'Test123!'
        })
        assert response.status_code == 200
        
        # Get accounts
        response = client.get('/api/mt5/accounts')
        
        assert response.status_code == 200
        data = response.json
        assert data['success'] is True
        assert len(data['accounts']) == 1
        assert data['accounts'][0]['mt5_login'] == '12345'
    
    def test_get_accounts_with_multiple_accounts(self, client, session):
        """Test getting accounts when user has multiple accounts"""
        from src.models.user import User
        from src.models.mt5_models import MT5Account
        
        # Create trader
        email = f'trader_{uuid.uuid4().hex[:8]}@test.com'
        user = User(email=email, first_name='Test', last_name='Trader', role='trader')
        user.set_password('Test123!')
        user.is_verified = True
        session.add(user)
        session.commit()
        
        # Create multiple MT5 accounts
        for i in range(3):
            mt5_account = MT5Account(
                user_id=user.id,
                mt5_login=f'1234{i}',
                mt5_password_encrypted='encrypted_password',
                mt5_group='demo\\\\forex',
                mt5_server='Demo-Server',
                balance=10000.0 + (i * 1000),
                equity=10000.0 + (i * 1000),
                status='active'
            )
            session.add(mt5_account)
        session.commit()
        
        # Login
        response = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': 'Test123!'
        })
        assert response.status_code == 200
        
        # Get accounts
        response = client.get('/api/mt5/accounts')
        
        assert response.status_code == 200
        data = response.json
        assert data['success'] is True
        assert len(data['accounts']) == 3


class TestMT5AccountDetails:
    """Test MT5 account details endpoint"""
    
    def test_get_account_not_found(self, client, session):
        """Test getting non-existent account"""
        from src.models.user import User
        
        # Create trader
        email = f'trader_{uuid.uuid4().hex[:8]}@test.com'
        user = User(email=email, first_name='Test', last_name='Trader', role='trader')
        user.set_password('Test123!')
        user.is_verified = True
        session.add(user)
        session.commit()
        
        # Login
        response = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': 'Test123!'
        })
        assert response.status_code == 200
        
        # Try to get non-existent account
        response = client.get('/api/mt5/accounts/99999')
        
        assert response.status_code == 404
    
    def test_get_account_unauthorized_access(self, client, session):
        """Test that users cannot access other users' accounts"""
        from src.models.user import User
        from src.models.mt5_models import MT5Account
        
        # Create first trader with account
        email1 = f'trader1_{uuid.uuid4().hex[:8]}@test.com'
        user1 = User(email=email1, first_name='Test', last_name='Trader1', role='trader')
        user1.set_password('Test123!')
        user1.is_verified = True
        session.add(user1)
        session.commit()
        
        mt5_account = MT5Account(
            user_id=user1.id,
            mt5_login='12345',
            mt5_password_encrypted='encrypted_password',
            mt5_group='demo\\\\forex',
            mt5_server='Demo-Server',
            balance=10000.0,
            status='active'
        )
        session.add(mt5_account)
        session.commit()
        account_id = mt5_account.id
        
        # Create second trader
        email2 = f'trader2_{uuid.uuid4().hex[:8]}@test.com'
        user2 = User(email=email2, first_name='Test', last_name='Trader2', role='trader')
        user2.set_password('Test123!')
        user2.is_verified = True
        session.add(user2)
        session.commit()
        
        # Login as second trader
        response = client.post('/api/v1/auth/login', json={
            'email': email2,
            'password': 'Test123!'
        })
        assert response.status_code == 200
        
        # Try to access first trader's account
        response = client.get(f'/api/mt5/accounts/{account_id}')
        
        # Should return 404 (not found) not 403, for security
        assert response.status_code == 404


class TestMT5Trades:
    """Test MT5 trades endpoint"""
    
    def test_get_trades_empty(self, client, session):
        """Test getting trades when account has none"""
        from src.models.user import User
        from src.models.mt5_models import MT5Account
        
        # Create trader
        email = f'trader_{uuid.uuid4().hex[:8]}@test.com'
        user = User(email=email, first_name='Test', last_name='Trader', role='trader')
        user.set_password('Test123!')
        user.is_verified = True
        session.add(user)
        session.commit()
        
        # Create MT5 account
        mt5_account = MT5Account(
            user_id=user.id,
            mt5_login='12345',
            mt5_password_encrypted='encrypted_password',
            mt5_group='demo\\\\forex',
            mt5_server='Demo-Server',
            balance=10000.0,
            status='active'
        )
        session.add(mt5_account)
        session.commit()
        account_id = mt5_account.id
        
        # Login
        response = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': 'Test123!'
        })
        assert response.status_code == 200
        
        # Get trades
        response = client.get(f'/api/mt5/accounts/{account_id}/trades')
        
        assert response.status_code == 200
        data = response.json
        assert data['success'] is True
        assert 'trades' in data
        assert len(data['trades']) == 0
    
    def test_get_trades_with_data(self, client, session):
        """Test getting trades when account has trades"""
        from src.models.user import User
        from src.models.mt5_models import MT5Account, MT5Trade
        from datetime import datetime
        
        # Create trader
        email = f'trader_{uuid.uuid4().hex[:8]}@test.com'
        user = User(email=email, first_name='Test', last_name='Trader', role='trader')
        user.set_password('Test123!')
        user.is_verified = True
        session.add(user)
        session.commit()
        
        # Create MT5 account
        mt5_account = MT5Account(
            user_id=user.id,
            mt5_login='12345',
            mt5_password_encrypted='encrypted_password',
            mt5_group='demo\\\\forex',
            mt5_server='Demo-Server',
            balance=10000.0,
            status='active'
        )
        session.add(mt5_account)
        session.commit()
        account_id = mt5_account.id
        
        # Create trade
        trade = MT5Trade(
            mt5_account_id=account_id,
            ticket='123456',
            symbol='EURUSD',
            trade_type='buy',
            volume=0.1,
            open_price=1.1000,
            close_price=1.1050,
            profit=50.0,
            open_time=datetime.utcnow(),
            close_time=datetime.utcnow()
        )
        session.add(trade)
        session.commit()
        
        # Login
        response = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': 'Test123!'
        })
        assert response.status_code == 200
        
        # Get trades
        response = client.get(f'/api/mt5/accounts/{account_id}/trades')
        
        assert response.status_code == 200
        data = response.json
        assert data['success'] is True
        assert len(data['trades']) == 1


class TestMT5Positions:
    """Test MT5 positions endpoint"""
    
    def test_get_positions_empty(self, client, session):
        """Test getting positions when account has none"""
        from src.models.user import User
        from src.models.mt5_models import MT5Account
        
        # Create trader
        email = f'trader_{uuid.uuid4().hex[:8]}@test.com'
        user = User(email=email, first_name='Test', last_name='Trader', role='trader')
        user.set_password('Test123!')
        user.is_verified = True
        session.add(user)
        session.commit()
        
        # Create MT5 account
        mt5_account = MT5Account(
            user_id=user.id,
            mt5_login='12345',
            mt5_password_encrypted='encrypted_password',
            mt5_group='demo\\\\forex',
            mt5_server='Demo-Server',
            balance=10000.0,
            status='active'
        )
        session.add(mt5_account)
        session.commit()
        account_id = mt5_account.id
        
        # Login
        response = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': 'Test123!'
        })
        assert response.status_code == 200
        
        # Get positions
        response = client.get(f'/api/mt5/accounts/{account_id}/positions')
        
        assert response.status_code == 200
        data = response.json
        assert data['success'] is True
        assert 'positions' in data
        assert len(data['positions']) == 0
    
    def test_get_positions_with_data(self, client, session):
        """Test getting positions when account has open positions"""
        from src.models.user import User
        from src.models.mt5_models import MT5Account, MT5Position
        from datetime import datetime
        
        # Create trader
        email = f'trader_{uuid.uuid4().hex[:8]}@test.com'
        user = User(email=email, first_name='Test', last_name='Trader', role='trader')
        user.set_password('Test123!')
        user.is_verified = True
        session.add(user)
        session.commit()
        
        # Create MT5 account
        mt5_account = MT5Account(
            user_id=user.id,
            mt5_login='12345',
            mt5_password_encrypted='encrypted_password',
            mt5_group='demo\\\\forex',
            mt5_server='Demo-Server',
            balance=10000.0,
            status='active'
        )
        session.add(mt5_account)
        session.commit()
        account_id = mt5_account.id
        
        # Create position
        position = MT5Position(
            mt5_account_id=account_id,
            ticket='789012',
            symbol='GBPUSD',
            position_type='sell',
            volume=0.2,
            price_open=1.2500,
            price_current=1.2480,
            profit=40.0,
            open_time=datetime.utcnow()
        )
        session.add(position)
        session.commit()
        
        # Login
        response = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': 'Test123!'
        })
        assert response.status_code == 200
        
        # Get positions
        response = client.get(f'/api/mt5/accounts/{account_id}/positions')
        
        assert response.status_code == 200
        data = response.json
        assert data['success'] is True
        assert len(data['positions']) == 1


class TestMT5AdminEndpoints:
    """Test MT5 admin endpoints"""
    
    def test_admin_accounts_requires_admin(self, client, session):
        """Test that admin endpoints require admin role"""
        from src.models.user import User
        
        # Create regular trader
        email = f'trader_{uuid.uuid4().hex[:8]}@test.com'
        user = User(email=email, first_name='Test', last_name='Trader', role='trader')
        user.set_password('Test123!')
        user.is_verified = True
        session.add(user)
        session.commit()
        
        # Login
        response = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': 'Test123!'
        })
        assert response.status_code == 200
        
        # Try to access admin endpoint
        response = client.get('/api/mt5/admin/accounts')
        
        assert response.status_code == 403
    
    def test_admin_accounts_requires_auth(self, client):
        """Test that admin endpoints require authentication"""
        response = client.get('/api/mt5/admin/accounts')
        assert response.status_code == 401
    
    def test_disable_account_requires_admin(self, client, session):
        """Test that disabling account requires admin role"""
        from src.models.user import User
        
        # Create regular trader
        email = f'trader_{uuid.uuid4().hex[:8]}@test.com'
        user = User(email=email, first_name='Test', last_name='Trader', role='trader')
        user.set_password('Test123!')
        user.is_verified = True
        session.add(user)
        session.commit()
        
        # Login
        response = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': 'Test123!'
        })
        assert response.status_code == 200
        
        # Try to disable account
        response = client.post('/api/mt5/admin/accounts/1/disable')
        
        assert response.status_code == 403
    
    def test_adjust_balance_requires_admin(self, client, session):
        """Test that adjusting balance requires admin role"""
        from src.models.user import User
        
        # Create regular trader
        email = f'trader_{uuid.uuid4().hex[:8]}@test.com'
        user = User(email=email, first_name='Test', last_name='Trader', role='trader')
        user.set_password('Test123!')
        user.is_verified = True
        session.add(user)
        session.commit()
        
        # Login
        response = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': 'Test123!'
        })
        assert response.status_code == 200
        
        # Try to adjust balance
        response = client.post('/api/mt5/admin/accounts/1/balance', json={
            'amount': 1000
        })
        
        assert response.status_code == 403
