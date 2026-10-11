import uuid
"""
Professional pytest configuration with proper Flask-SQLAlchemy integration
"""
import pytest
import os
import sys
from flask import Flask
from sqlalchemy.orm import scoped_session, sessionmaker
from datetime import datetime, timedelta

# Test mode must be selected before app.py can patch sockets or initialize I/O.
os.environ["FLASK_TESTING"] = "true"

# Import app factory
from src.app import create_app
from src.database import db as _db
from src.models.user import User
from src.models.user import EmailVerificationToken

# Import test configs
from test_config import SQLiteTestConfig, PostgreSQLTestConfig


# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================

def pytest_addoption(parser):
    """Add custom command line options"""
    parser.addoption(
        "--use-postgres",
        action="store_true",
        default=False,
        help="Use PostgreSQL test database instead of SQLite"
    )


# ============================================================================
# SESSION SCOPE FIXTURES (Created once per test session)
# ============================================================================

@pytest.fixture(scope='session')
def app(request):
    """Create Flask app for testing"""
    import os
    from src.app import create_app
    from src.config import TestingConfig
    
    # Set FLASK_TESTING env var to disable Talisman
    os.environ['FLASK_TESTING'] = 'true'
    
    # Create app
    if request.config.getoption('--use-postgres'):
        test_url = os.environ.get('TEST_DATABASE_URL')
        if not test_url:
            raise pytest.UsageError('--use-postgres requires an isolated TEST_DATABASE_URL')
    else:
        test_url = 'sqlite:///:memory:'
    app = create_app('testing', config_overrides={'SQLALCHEMY_DATABASE_URI': test_url})
    
    # Establish application context
    ctx = app.app_context()
    ctx.push()
    
    yield app
    
    # Cleanup
    ctx.pop()


@pytest.fixture(scope='session')
def database():
    """Create database tables"""
    # Note: _db is already initialized via init_db() in app creation
    # We don't need app parameter here as _db is a global object
    
    yield _db
    
    # Tables are cleaned by session fixture's TRUNCATE
    # No need to drop tables as they're reused across test sessions
    pass


# ============================================================================
# FUNCTION SCOPE FIXTURES (Created for each test)
# ============================================================================

@pytest.fixture(scope='function')
def session(app, database):
    """
    Create a new database session for each test with proper isolation.
    Uses nested transactions to ensure complete rollback after each test.
    
    Fixed: Improved connection pooling and cleanup for flaky tests.
    """
    with app.app_context():
        # Start a connection
        connection = database.engine.connect()
        
        # Begin a non-ORM transaction
        transaction = connection.begin()
        
        # Create a session bound to the connection
        session_factory = sessionmaker(bind=connection)
        Session = scoped_session(session_factory)
        
        # Override Flask-SQLAlchemy's session
        database.session = Session
        
        yield Session
        
        # Cleanup - ensure proper teardown
        try:
            # Expire all objects to avoid stale data
            Session.expire_all()
            # Remove the session
            Session.remove()
            # Rollback the transaction
            transaction.rollback()
            
            # Clear Redis cache to prevent test contamination
            try:
                from src.database import redis_client
                if redis_client:
                    redis_client.flushdb()
            except Exception:
                pass  # Redis might not be available in all tests
                
        except Exception as e:
            print(f"Session cleanup warning: {e}")
        finally:
            try:
                # Close the connection
                connection.close()
                # Dispose of the engine pool to prevent connection leaks
                database.engine.dispose()
            except Exception as e:
                print(f"Connection cleanup warning: {e}")


@pytest.fixture(scope='function')
def client(app, session):
    """Create Flask test client"""
    with app.test_client() as client:
        yield client


# ============================================================================
# USER FIXTURES
# ============================================================================

@pytest.fixture
def test_user(session):
    """Create a test user"""
    user = User(
        email='test@example.com',
        first_name='Test',
        last_name='User',
        role='trader',
        is_active=True,
        is_verified=True
    )
    user.set_password('TestPassword123!')
    session.add(user)
    session.commit()
    return user


@pytest.fixture
def admin_user(session):
    """Create an admin user (master role)"""
    user = User(
        email='admin@example.com',
        first_name='Admin',
        last_name='User',
        role='master',  # Master can create affiliates and traders
        is_active=True,
        is_verified=True,
        can_create_same_role=False
    )
    user.set_password('AdminPassword123!')
    session.add(user)
    session.commit()
    return user


@pytest.fixture
def master_user(session):
    """Create a master user"""
    user = User(
        email='master@example.com',
        first_name='Master',
        last_name='User',
        role='master',
        is_active=True,
        is_verified=True
    )
    user.set_password('MasterPassword123!')
    session.add(user)
    session.commit()
    return user


@pytest.fixture
def affiliate_user(session, super_admin_user):
    """Create an affiliate user"""
    user = User(
        email='affiliate@example.com',
        first_name='Affiliate',
        last_name='User',
        role='affiliate',
        is_active=True,
        is_verified=True,
        parent_id=super_admin_user.id
    )
    user.set_password('AffiliatePassword123!')
    session.add(user)
    session.commit()
    session.refresh(user)  # Refresh to load parent relationship
    user.update_tree_path()
    session.commit()
    user.generate_referral_code()
    session.commit()
    return user


@pytest.fixture
def super_admin_user(session):
    """Create a super admin user (root)"""
    user = User(
        email='superadmin@example.com',
        first_name='Super',
        last_name='Admin',
        role='super_admin',
        is_active=True,
        is_verified=True,
        can_create_same_role=True,
        parent_id=None  # Root user
    )
    user.set_password('SuperAdminPassword123!')
    session.add(user)
    session.commit()
    user.update_tree_path()
    session.commit()
    return user


@pytest.fixture
def trader_user(session, super_admin_user):
    """Create a trader user"""
    import uuid
    unique_email = f'trader-{uuid.uuid4().hex[:8]}@example.com'
    user = User(
        email=unique_email,
        first_name='Trader',
        last_name='User',
        role='trader',
        is_active=True,
        is_verified=True,
        parent_id=super_admin_user.id
    )
    user.set_password('TraderPassword123!')
    session.add(user)
    session.commit()
    user.update_tree_path()
    session.commit()
    return user


# ============================================================================
# AUTH FIXTURES
# ============================================================================

@pytest.fixture
def auth_headers(test_user):
    """Get authentication headers for test user"""
    token = test_user.generate_access_token()
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def admin_auth_headers(admin_user):
    """Get authentication headers for admin user"""
    token = admin_user.generate_access_token()
    return {'Authorization': f'Bearer {token}'}


# ============================================================================
# MOCK FIXTURES
# ============================================================================

@pytest.fixture
def mock_sendgrid(mocker):
    """Mock SendGrid email service"""
    # Mock SendGrid API client
    mock_response = mocker.Mock()
    mock_response.status_code = 202
    mock_response.body = '{}'
    mock_response.headers = {}
    
    mock_sg = mocker.Mock()
    mock_sg.send.return_value = mock_response
    
    return mocker.patch('sendgrid.SendGridAPIClient', return_value=mock_sg)


@pytest.fixture
def mock_nowpayments(mocker):
    """Mock NowPayments API"""
    return mocker.patch('src.services.nowpayments_service.create_payment')


@pytest.fixture
def mock_discord(mocker):
    """Mock Discord webhook"""
    return mocker.patch('src.services.discord_service.send_notification')


# ============================================================================
# TIME FIXTURES
# ============================================================================

@pytest.fixture
def freeze_time(mocker):
    """Freeze time for testing time-sensitive features"""
    frozen_time = datetime(2025, 1, 1, 12, 0, 0)
    mocker.patch('datetime.datetime').utcnow.return_value = frozen_time
    return frozen_time


@pytest.fixture
def unverified_user(session, super_admin_user):
    """Create an unverified user"""
    user = User(
        email='unverified@example.com',
        first_name='Unverified',
        last_name='User',
        role='trader',
        is_active=True,
        is_verified=False,
        parent_id=super_admin_user.id
    )
    user.set_password('UnverifiedPassword123!')
    session.add(user)
    session.commit()
    session.refresh(user)
    user.update_tree_path()
    session.commit()
    return user

@pytest.fixture
def agent_user(session, super_admin_user):
    """Create an agent user with agent profile"""
    from src.models import Agent
    
    user = User(
        email='agent@example.com',
        first_name='Agent',
        last_name='User',
        role='affiliate',
        is_active=True,
        is_verified=True,
        parent_id=super_admin_user.id
    )
    user.set_password('AgentPassword123!')
    session.add(user)
    session.commit()
    session.refresh(user)
    user.update_tree_path()
    session.commit()
    
    # Create agent profile
    agent = Agent(
        user_id=user.id,
        agent_code='AGENT001',
        commission_rate=10.0,
        is_active=True
    )
    session.add(agent)
    session.commit()
    
    return user

@pytest.fixture
def referral_user(session, agent_user, super_admin_user):
    """Create a referred user"""
    from src.models import Agent, Referral
    
    user = User(
        email='referred@example.com',
        first_name='Referred',
        last_name='User',
        role='trader',
        is_active=True,
        is_verified=True,
        parent_id=super_admin_user.id
    )
    user.set_password('ReferredPassword123!')
    session.add(user)
    session.commit()
    session.refresh(user)
    user.update_tree_path()
    session.commit()
    
    # Create referral record
    agent = session.query(Agent).filter_by(user_id=agent_user.id).first()
    referral = Referral(
        agent_id=agent.id,
        referred_user_id=user.id,
        referral_code='AGENT001',
        status='active'
    )
    session.add(referral)
    session.commit()
    
    return user

@pytest.fixture
def tenant(session):
    """Create a tenant"""
    from src.models import Tenant
    
    tenant = Tenant(
        name='Test Tenant',
        subdomain=f"test_{uuid.uuid4().hex[:8]}",
        status="active"
    )
    session.add(tenant)
    session.commit()
    
    return tenant

@pytest.fixture
def trading_program(session, tenant):
    """Create a trading program"""
    from src.models import TradingProgram
    
    program = TradingProgram(
        tenant_id=tenant.id,
        name='Standard Challenge',
        type='one_phase',
        description='Standard trading challenge',
        account_size=10000.0,
        profit_target=10.0,  # 10%
        max_daily_loss=5.0,  # 5%
        max_total_loss=10.0,  # 10%
        price=100.0,
        profit_split=80.0,
        is_active=True
    )
    session.add(program)
    session.commit()
    
    return program

@pytest.fixture
def challenge(session, trader_user, trading_program):
    """Create a challenge"""
    from src.models import Challenge
    
    challenge = Challenge(
        user_id=trader_user.id,
        program_id=trading_program.id,
        status='active',
        initial_balance=10000.0,
        current_balance=10000.0
    )
    session.add(challenge)
    session.commit()
    
    return challenge

@pytest.fixture
def referral(session, agent_user, referral_user):
    """Create a referral record"""
    from src.models.referral import Referral
    from src.models.agent import Agent
    
    # Get the agent
    agent = session.query(Agent).filter_by(user_id=agent_user.id).first()
    
    # Create referral
    referral = Referral(
        agent_id=agent.id,
        referred_user_id=referral_user.id,
        referral_code='TEST123',
        status='active'
    )
    session.add(referral)
    session.commit()
    return referral

@pytest.fixture
def trader_auth_headers(trader_user):
    """Create auth headers for trader user"""
    access_token = trader_user.generate_access_token()
    return {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }



# ============================================================================


# ============================================================================
# MOCK FIXTURES (For external services)
# ============================================================================

@pytest.fixture(autouse=True)
def mock_email_service(monkeypatch):
    """
    Mock EmailService to avoid actual email sending in tests.
    Applied automatically to all tests (autouse=True).
    """
    def mock_send(*args, **kwargs):
        # Simulate successful email sending
        return True
    
    # Mock the EmailService class methods
    monkeypatch.setattr('src.services.email_service.EmailService._send_email', mock_send)
    monkeypatch.setattr('src.services.email_service.EmailService.send_verification_email', mock_send)
    monkeypatch.setattr('src.services.email_service.EmailService.send_password_reset_email', mock_send)
    
    return mock_send

# HELPER FUNCTIONS (For common test patterns)
# ============================================================================

def register_user_helper(client, email='test@example.com', password='Test123!@#', 
                        first_name='Test', last_name='User', **kwargs):
    """
    Helper function to register a user.
    Returns the response object.
    """
    data = {
        'email': email,
        'password': password,
        'first_name': first_name,
        'last_name': last_name,
        **kwargs
    }
    return client.post('/api/auth/register', json=data)


def verify_user_helper(client, email, verification_code):
    """
    Helper function to verify a user's email.
    Returns the response object.
    """
    return client.post('/api/auth/verify-email', json={
        'email': email,
        'code': verification_code
    })


def login_user_helper(client, email='test@example.com', password='Test123!@#'):
    """
    Helper function to login a user.
    Returns the response object.
    """
    return client.post('/api/auth/login', json={
        'email': email,
        'password': password
    })


def register_and_login_user(client, email='test@example.com', password='Test123!@#',
                            first_name='Test', last_name='User'):
    """
    Helper function to register, verify, and login a user in one go.
    Returns the access token.
    """
    # Register
    response = register_user_helper(client, email, password, first_name, last_name)
    if response.status_code != 201:
        raise Exception(f'Registration failed: {response.get_json()}')
    
    data = response.get_json()
    
    # If verification code is returned, verify the user
    if 'verification_code' in data:
        verification_code = data['verification_code']
        verify_response = verify_user_helper(client, email, verification_code)
        if verify_response.status_code not in [200, 201]:
            raise Exception(f'Verification failed: {verify_response.get_json()}')
    
    # Login to get access token
    login_response = login_user_helper(client, email, password)
    if login_response.status_code != 200:
        raise Exception(f'Login failed: {login_response.get_json()}')
    
    login_data = login_response.get_json()
    return login_data.get('access_token')


def get_auth_headers(token):
    """
    Helper function to create authorization headers.
    """
    return {'Authorization': f'Bearer {token}'}

# ============================================================================
# COOKIE-BASED AUTH HELPERS (For httpOnly cookie migration)
# ============================================================================

def extract_token_from_cookies(response, token_name='access_token'):
    """
    Extract token from httpOnly cookies in response.
    Returns the token value or None if not found.
    """
    cookies = response.headers.getlist('Set-Cookie')
    for cookie in cookies:
        if cookie.startswith(f'{token_name}='):
            # Extract token value from cookie string
            # Format: access_token=<value>; HttpOnly; Secure; SameSite=Lax; Max-Age=3600; Path=/
            token_part = cookie.split(';')[0]
            token_value = token_part.split('=', 1)[1]
            return token_value
    return None

def login_user_helper_with_cookies(client, email='test@example.com', password='Test123!@#'):
    """
    Helper function to login a user with cookie support.
    Returns a tuple: (access_token, refresh_token, response)
    """
    response = client.post('/api/auth/login', json={
        'email': email,
        'password': password
    })
    
    if response.status_code != 200:
        return None, None, response
    
    # Extract tokens from cookies
    access_token = extract_token_from_cookies(response, 'access_token')
    refresh_token = extract_token_from_cookies(response, 'refresh_token')
    
    return access_token, refresh_token, response

def register_and_login_user_with_cookies(client, email='test@example.com', password='Test123!@#',
                                         first_name='Test', last_name='User'):
    """
    Helper function to register, verify, and login a user with cookie support.
    Returns a tuple: (access_token, refresh_token)
    """
    # Register
    response = register_user_helper(client, email, password, first_name, last_name)
    if response.status_code != 201:
        raise Exception(f'Registration failed: {response.get_json()}')
    
    data = response.get_json()
    
    # If verification code is returned, verify the user
    if 'verification_code' in data:
        verification_code = data['verification_code']
        verify_response = verify_user_helper(client, email, verification_code)
        if verify_response.status_code not in [200, 201]:
            raise Exception(f'Verification failed: {verify_response.get_json()}')
    
    # Login to get access token from cookies
    access_token, refresh_token, login_response = login_user_helper_with_cookies(client, email, password)
    if login_response.status_code != 200:
        raise Exception(f'Login failed: {login_response.get_json()}')
    
    return access_token, refresh_token

@pytest.fixture(scope='function')
def session(db_engine):
    """Creates a new database session for a test."""
    connection = db_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture(scope='session')
def db_engine(app):
    """Yields a SQLAlchemy engine for the test database."""
    from src.extensions import db; return db.engine
