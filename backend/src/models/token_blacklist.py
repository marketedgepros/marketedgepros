from src.database import db
from datetime import datetime

class TokenBlacklist(db.Model):
    """Model for storing revoked JWT tokens"""
    __tablename__ = "token_blacklist"
    
    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(36), nullable=False, unique=True, index=True)
    token_type = db.Column(db.String(10), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    revoked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    
    user = db.relationship("User", backref=db.backref("revoked_tokens", lazy="dynamic"))
    
    def __repr__(self):
        return f"<TokenBlacklist {self.jti}>"
    
    @classmethod
    def is_token_revoked(cls, jti):
        """Check if a token is revoked"""
        return cls.query.filter_by(jti=jti).first() is not None
    
    @classmethod
    def revoke_token(cls, jti, token_type, user_id, expires_at):
        """Add a token to the blacklist"""
        if cls.is_token_revoked(jti):
            return False
        
        blacklisted_token = cls(
            jti=jti,
            token_type=token_type,
            user_id=user_id,
            expires_at=expires_at
        )
        db.session.add(blacklisted_token)
        db.session.commit()
        return True
    
    @classmethod
    def revoke_all_user_tokens(cls, user_id):
        """Revoke all tokens for a user (useful for security incidents)"""
        from src.models.user import User
        user = User.query.get(user_id)
        if user:
            user.token_version = (user.token_version or 0) + 1
            db.session.commit()
            return True
        return False
    
    @classmethod
    def cleanup_expired_tokens(cls):
        """Remove expired tokens from blacklist (run periodically)"""
        expired = cls.query.filter(cls.expires_at < datetime.utcnow()).all()
        for token in expired:
            db.session.delete(token)
        db.session.commit()
        return len(expired)
