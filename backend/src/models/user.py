"""User model with authentication and security features"""
from src.database import db, TimestampMixin
from werkzeug.security import generate_password_hash, check_password_hash
import pyotp
import secrets
from datetime import datetime, timedelta
import jwt
from flask import current_app
from src.constants.roles import Roles, ROLE_HIERARCHY
from src.utils.hierarchy_scoping import (
    HierarchyScopedMixin,
    complete_hierarchy_scope,
    escape_hierarchy_path,
    legacy_root_scope,
    tenant_hierarchy_scope,
)


class User(db.Model, TimestampMixin, HierarchyScopedMixin):
    """User model with authentication support and hierarchy filtering"""
    
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # Personal Information
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    country_code = db.Column(db.String(2))
    date_of_birth = db.Column(db.Date)
    avatar_url = db.Column(db.String(500))  # Profile picture URL
    
    # Account Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    email_verified_at = db.Column(db.DateTime)
    
    # Two-Factor Authentication
    two_factor_enabled = db.Column(db.Boolean, default=False, nullable=False)
    two_factor_secret = db.Column(db.String(32))
    
    # KYC Status
    kyc_status = db.Column(db.String(20), default='not_submitted')  # not_submitted, pending, approved, rejected
    kyc_submitted_at = db.Column(db.DateTime)
    kyc_verified_at = db.Column(db.DateTime)
    kyc_approved_at = db.Column(db.DateTime)
    kyc_approved_by = db.Column(db.Integer)  # Admin user ID
    kyc_rejected_at = db.Column(db.DateTime)
    kyc_rejected_by = db.Column(db.Integer)  # Admin user ID
    kyc_rejection_reason = db.Column(db.Text)
    kyc_admin_notes = db.Column(db.Text)
    
    # KYC Documents - ID Proof
    kyc_id_status = db.Column(db.String(20), default='not_uploaded')  # not_uploaded, pending, approved, rejected
    kyc_id_url = db.Column(db.String(500))  # Document URL
    kyc_id_uploaded_at = db.Column(db.DateTime)
    kyc_id_notes = db.Column(db.Text)
    
    # KYC Documents - Address Proof
    kyc_address_status = db.Column(db.String(20), default='not_uploaded')
    kyc_address_url = db.Column(db.String(500))
    kyc_address_uploaded_at = db.Column(db.DateTime)
    kyc_address_notes = db.Column(db.Text)

    # Financial / Payout Fields
    available_balance = db.Column(db.Numeric(12, 2), default=0.00)
    total_withdrawn = db.Column(db.Numeric(12, 2), default=0.00)
    payout_count = db.Column(db.Integer, default=0)
    
    # KYC Documents - Selfie
    kyc_selfie_status = db.Column(db.String(20), default='not_uploaded')
    kyc_selfie_url = db.Column(db.String(500))
    kyc_selfie_uploaded_at = db.Column(db.DateTime)
    kyc_selfie_notes = db.Column(db.Text)
    
    # KYC Documents - Bank Statement
    kyc_bank_status = db.Column(db.String(20), default='not_uploaded')
    kyc_bank_url = db.Column(db.String(500))
    kyc_bank_uploaded_at = db.Column(db.DateTime)
    kyc_bank_notes = db.Column(db.Text)
    
    # Role and Permissions
    role = db.Column(db.String(20), default='guest', nullable=False)  # supermaster, master, agent, trader, guest
    token_version = db.Column(db.Integer, default=0, nullable=False)  # For token revocation
    can_create_same_role = db.Column(db.Boolean, default=False, nullable=False)  # Only root supermaster can create another supermaster
    
    # Hierarchy (MLM Structure)
    parent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)  # Who created this user
    level = db.Column(db.Integer, default=0, nullable=False, index=True)  # Depth in hierarchy (0 = top)
    tree_path = db.Column(db.String(500), index=True)  # Path in tree: "1/5/23/45" for fast queries
    commission_rate = db.Column(db.Numeric(5, 2), default=0.00)  # Custom commission rate for this user
    referral_code = db.Column(db.String(20), unique=True, nullable=True, index=True)  # Unique referral code for agents/masters
    
    # Tenant (White Label)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True)
    
    # Last Login
    last_login_at = db.Column(db.DateTime)
    last_login_ip = db.Column(db.String(45))
    
    # Relationships
    tenant = db.relationship('Tenant', back_populates='users')
    challenges = db.relationship('Challenge', back_populates='user', lazy='dynamic', foreign_keys='Challenge.user_id')
    created_challenges = db.relationship('Challenge', back_populates='creator', lazy='dynamic', foreign_keys='Challenge.created_by')
    
    # Hierarchy Relationships
    parent = db.relationship('User', remote_side=[id], backref='children', foreign_keys=[parent_id])

    # Add indexes for performance
    __table_args__ = (db.Index('ix_user_tenant_id', 'tenant_id'),)
    # children accessible via backref
    
    def __repr__(self):
        return f'<User {self.email}>'
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verify password"""
        return check_password_hash(self.password_hash, password)
    
    def generate_referral_code(self):
        """Generate unique referral code"""
        import secrets
        import string
        
        # Only agents and masters get referral codes
        if not Roles.is_admin(self.role) and self.role != Roles.AFFILIATE:
            return None
        
        # Bounded retries; the unique DB index remains the concurrency gate.
        for _attempt in range(32):
            code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            if not User.query.filter_by(referral_code=code).first():
                self.referral_code = code
                return code
        raise RuntimeError('Unable to allocate a unique referral code')
    
    def generate_2fa_secret(self):
        """Generate new 2FA secret"""
        self.two_factor_secret = pyotp.random_base32()
        return self.two_factor_secret
    
    def get_2fa_uri(self):
        """Get 2FA URI for QR code"""
        if not self.two_factor_secret:
            self.generate_2fa_secret()
        
        totp = pyotp.TOTP(self.two_factor_secret)
        return totp.provisioning_uri(
            name=self.email,
            issuer_name='MarketEdgePros'
        )
    
    def verify_2fa_token(self, token):
        """Verify 2FA token"""
        # Check if secret exists (can be used during setup or when enabled)
        if not self.two_factor_secret:
            return False
        
        totp = pyotp.TOTP(self.two_factor_secret)
        return totp.verify(token, valid_window=1)
    
    def generate_verification_token(self, expires_in_hours=24):
        """Generate a new email verification token for the user."""
        try:
            # Create a new token instance
            token_instance = EmailVerificationToken(user_id=self.id, expires_in_hours=expires_in_hours)
            
            # Add the token to the session and commit to save it
            db.session.add(token_instance)
            db.session.commit()
            
            # Return the token string
            return token_instance.code
        except Exception as e:
            db.session.rollback()
            # Log the exception if necessary
            raise RuntimeError("Failed to generate verification token") from e
    
    def generate_password_reset_token(self, expires_in_minutes=15):
        """Generate a new password reset token for the user."""
        try:
            # Create a new token instance
            token_instance = PasswordResetToken(user_id=self.id, expires_in_minutes=expires_in_minutes)
            
            # Add the token to the session and commit to save it
            db.session.add(token_instance)
            db.session.commit()
            
            # Return the 6-digit code
            return token_instance.code
        except Exception as e:
            db.session.rollback()
            # Log the exception if necessary
            raise RuntimeError("Failed to generate password reset token") from e
    
    def generate_access_token(self, session_id=None):
        """Generate JWT access token with jti and token_version"""
        import uuid
        now = datetime.utcnow()
        expires_delta = current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
        payload = {
            'user_id': self.id,
            'email': self.email,
            'role': self.role,
            'tenant_id': self.tenant_id,
            'exp': now + expires_delta,
            'iat': now,
            'type': 'access',
            'jti': str(uuid.uuid4()),  # Unique token ID for revocation
            'token_version': self.token_version or 0  # For mass revocation
        }
        
        if session_id is not None:
            payload['sid'] = session_id

        return jwt.encode(
            payload,
            current_app.config['JWT_SECRET_KEY'],
            algorithm='HS256'
        )
    
    def generate_refresh_token(self, session_id=None):
        """Generate JWT refresh token"""
        now = datetime.utcnow()
        expires_delta = current_app.config['JWT_REFRESH_TOKEN_EXPIRES']
        payload = {
            'user_id': self.id,
            'exp': now + expires_delta,
            'iat': now,
            'type': 'refresh',
            'jti': __import__('uuid').uuid4().hex,
            'token_version': self.token_version or 0
        }

        if session_id is not None:
            payload['sid'] = session_id

        return jwt.encode(
            payload,
            current_app.config['JWT_SECRET_KEY'],
            algorithm='HS256'
        )
    
    @staticmethod
    def verify_token(token, token_type='access'):
        """Verify JWT token"""
        try:
            payload = jwt.decode(
                token,
                current_app.config['JWT_SECRET_KEY'],
                algorithms=['HS256'],
                options={'require': ['user_id', 'type', 'exp', 'iat']}
            )
            
            if payload.get('type') != token_type:
                return None
            
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    def update_last_login(self, ip_address=None):
        """Update last login timestamp and IP"""
        self.last_login_at = datetime.utcnow()
        if ip_address:
            self.last_login_ip = ip_address
        db.session.commit()
    
    # Hierarchy Methods
    MAX_ANCESTOR_DEPTH = 128

    @staticmethod
    def _is_positive_integer(value):
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    @classmethod
    def _is_canonical_path_for_id(cls, path, user_id):
        """Validate the slash-delimited format written for newly created paths."""
        if not isinstance(path, str) or not path or len(path) > 500:
            return False
        segments = path.split('/')
        return (
            bool(segments)
            and all(segment.isdigit() and str(int(segment)) == segment and int(segment) > 0
                    for segment in segments)
            and segments[-1] == str(user_id)
        )

    def _descendants_query(self):
        """Return the slash-bounded descendant query, or no query for an invalid path."""
        path = self.tree_path
        if not isinstance(path, str) or not path.strip() or len(path) > 500:
            return None
        escaped_path = escape_hierarchy_path(path)
        query = User.query.filter(User.tree_path.like(f"{escaped_path}/%", escape="\\"))
        if legacy_root_scope(self):
            return query
        if not tenant_hierarchy_scope(self):
            return None
        return query.filter(User.tenant_id == self.tenant_id)

    def get_all_descendants(self):
        """Get all users in the downline using a literal, slash-bounded prefix."""
        query = self._descendants_query()
        return query.all() if query is not None else []
    
    def get_direct_children(self):
        """Get only direct children (1 level down)"""
        return self.children
    
    def get_ancestors(self):
        """Get the upline while refusing cycles and unbounded malformed chains."""
        ancestors = []
        self_id = getattr(self, 'id', None)
        visited = {('id', self_id)} if self_id is not None else {('object', id(self))}
        current = getattr(self, 'parent', None)
        max_depth = getattr(self, 'MAX_ANCESTOR_DEPTH', 128)

        while current is not None:
            current_id = getattr(current, 'id', None)
            marker = ('id', current_id) if current_id is not None else ('object', id(current))
            if marker in visited:
                raise ValueError('Hierarchy ancestry contains a cycle')
            if len(ancestors) >= max_depth:
                raise ValueError('Hierarchy ancestry exceeds the maximum depth')
            visited.add(marker)
            ancestors.append(current)
            current = getattr(current, 'parent', None)
        return ancestors
    
    def update_tree_path(self):
        """Write a canonical slash-delimited path for a valid parent relationship."""
        if not self._is_positive_integer(self.id):
            raise ValueError('Cannot build hierarchy path')

        parent = self.parent
        if parent is None:
            if self.parent_id is not None:
                raise ValueError('Cannot build hierarchy path')
            self.tree_path = str(self.id)
            self.level = 0
            return

        if not self._is_positive_integer(parent.id):
            raise ValueError('Cannot build hierarchy path')
        parent_path = parent.tree_path
        if not self._is_canonical_path_for_id(parent_path, parent.id):
            raise ValueError('Cannot build hierarchy path')
        if str(self.id) in parent_path.split('/'):
            raise ValueError('Cannot build hierarchy path')
        new_path = f"{parent_path}/{self.id}"
        if len(new_path) > 500 or not isinstance(parent.level, int) or isinstance(parent.level, bool) or parent.level < 0:
            raise ValueError('Cannot build hierarchy path')
        self.tree_path = new_path
        self.level = parent.level + 1
    
    def can_create_user(self, target_role):
        """Check if this user can create a user with target_role"""
        from src.constants.roles import can_user_create_role, Roles
        
        # Normalize roles
        current_role = Roles.normalize_role(self.role)
        target = Roles.normalize_role(target_role)
        
        # Use the centralized role hierarchy check
        from src.utils.hierarchy_scoping import platform_root_scope
        if not current_app.config.get('EXPANDED_HIERARCHY_ENABLED', False):
            return platform_root_scope(self) and target in {Roles.AFFILIATE, Roles.TRADER}
        return can_user_create_role(current_role, target, platform_root_scope(self))
    
    def get_downline_count(self):
        """Get total count of users in downline without materializing every row."""
        query = self._descendants_query()
        return query.count() if query is not None else 0
    
    def get_downline_by_level(self, max_level=None):
        """Get downline organized by level"""
        result = {}
        for user in self.get_all_descendants():
            level_diff = user.level - self.level
            if max_level and level_diff > max_level:
                continue
            if level_diff not in result:
                result[level_diff] = []
            result[level_diff].append(user)
        return result
    
    def to_dict(self, include_sensitive=False):
        """Convert user to dictionary"""
        data = {
            'id': self.id,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'phone': self.phone,
            'country_code': self.country_code,
            'is_active': self.is_active,
            'is_verified': self.is_verified,
            'two_factor_enabled': self.two_factor_enabled,
            'kyc_status': self.kyc_status,
            'role': self.role,
            'tenant_id': self.tenant_id,
            'avatar_url': self.avatar_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None
        }
        
        if include_sensitive:
            data['email_verified_at'] = self.email_verified_at.isoformat() if self.email_verified_at else None
            data['kyc_submitted_at'] = self.kyc_submitted_at.isoformat() if self.kyc_submitted_at else None
            data['kyc_verified_at'] = self.kyc_verified_at.isoformat() if self.kyc_verified_at else None
        
        return data
    
    @classmethod
    def hierarchy_filter_for_entity(cls, current_user):
        """
        Custom hierarchy filter for User model.
        Returns users in current_user's hierarchy (downline).
        
        Args:
            current_user: The current logged-in user
            
        Returns:
            SQLAlchemy filter condition or None (if supermaster)
        """
        if not complete_hierarchy_scope(current_user):
            from sqlalchemy import false
            return false()
        if legacy_root_scope(current_user):
            return None
        if not tenant_hierarchy_scope(current_user):
            from sqlalchemy import false
            return false()
        path = escape_hierarchy_path(current_user.tree_path)
        return ((cls.tenant_id == current_user.tenant_id)
                & ((cls.id == current_user.id)
                   | cls.tree_path.like(f"{path}/%", escape="\\")))


class EmailVerificationToken(db.Model, TimestampMixin):
    """Email verification tokens"""
    
    __tablename__ = 'email_verification_tokens'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    code = db.Column(db.String(6), nullable=False, index=True)  # 6-digit code
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)  # For URL verification
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    
    user = db.relationship('User', backref='verification_tokens')
    
    def __init__(self, user_id, expires_in_hours=24):
        self.user_id = user_id
        self.code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])  # Generate 6-digit code
        self.token = secrets.token_urlsafe(32)  # For URL-based verification
        self.expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)
    
    def is_valid(self):
        """Check if token is valid"""
        return not self.used and datetime.utcnow() < self.expires_at
    
    def mark_as_used(self):
        """Mark token as used"""
        self.used = True
        db.session.commit()



# ============================================================================
# MLM Hierarchy Event Listeners - Auto-fix tree_path and prevent loops
# ============================================================================

from sqlalchemy import event

@event.listens_for(User.parent_id, 'set')
def prevent_hierarchy_loop(target, value, oldvalue, initiator):
    """Prevent user from becoming their own ancestor"""
    if value is None:
        return value
    
    # Can't be your own parent
    if value == target.id:
        raise ValueError("User cannot be their own parent")
    
    # Check if new parent is a descendant of this user
    if target.id:  # Only check for existing users
        new_parent = User.query.get(value)
        if new_parent and new_parent.tree_path and target.tree_path:
            # If new parent's tree_path starts with this user's path, it's a descendant
            if new_parent.tree_path.startswith(target.tree_path + '/') or new_parent.tree_path == target.tree_path:
                raise ValueError("Cannot set parent to a descendant (would create hierarchy loop)")
    
    return value


@event.listens_for(User, 'after_update')
def auto_update_tree_path_on_parent_change(mapper, connection, target):
    """Automatically update tree_path when parent changes"""
    # Check if parent_id changed
    history = db.inspect(target).attrs.parent_id.history
    if history.has_changes():
        # Update this user's tree_path
        target.update_tree_path()
        
        # Update all descendants' tree_paths
        if target.tree_path:
            descendants = User.query.filter(
                User.tree_path.like(f"{target.tree_path}/%")
            ).all()
            for descendant in descendants:
                descendant.update_tree_path()
                db.session.add(descendant)



class PasswordResetToken(db.Model, TimestampMixin):
    """Password reset tokens"""
    
    __tablename__ = 'password_reset_tokens'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    code = db.Column(db.String(6), nullable=False, index=True)  # 6-digit code
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)  # For URL reset
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    
    user = db.relationship('User', backref='reset_tokens')
    
    def __init__(self, user_id, expires_in_minutes=15):
        self.user_id = user_id
        self.code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])  # Generate 6-digit code
        self.token = secrets.token_urlsafe(32)  # For URL-based reset
        self.expires_at = datetime.utcnow() + timedelta(minutes=expires_in_minutes)
    
    def is_valid(self):
        """Check if token is valid"""
        return not self.used and datetime.utcnow() < self.expires_at
    
    def mark_as_used(self):
        """Mark token as used"""
        self.used = True
        db.session.commit()
