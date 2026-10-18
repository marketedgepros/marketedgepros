"""
Verification Attempt model for tracking email verification attempts
"""
from src.database import db, TimestampMixin
from datetime import datetime


class VerificationAttempt(db.Model, TimestampMixin):
    """Track email verification attempts for security and rate limiting"""
    
    __tablename__ = 'verification_attempts'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    code_entered = db.Column(db.String(6), nullable=False)
    success = db.Column(db.Boolean, default=False, nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4 or IPv6
    user_agent = db.Column(db.String(500), nullable=True)
    failure_reason = db.Column(db.String(200), nullable=True)  # invalid_code, expired, already_used, etc.
    
    # Indexes for efficient queries
    __table_args__ = (
        db.Index('idx_email_created', 'email', 'created_at'),
        db.Index('idx_ip_created', 'ip_address', 'created_at'),
        db.Index('idx_success_created', 'success', 'created_at'),
    )
    
    def __repr__(self):
        return f'<VerificationAttempt {self.email} - {"Success" if self.success else "Failed"}>'
    
    @staticmethod
    def log_attempt(email, code_entered, success, ip_address=None, user_agent=None, failure_reason=None):
        """Log a verification attempt"""
        attempt = VerificationAttempt(
            email=email,
            code_entered='******',
            success=success,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason=failure_reason
        )
        db.session.add(attempt)
        db.session.commit()
        return attempt
    
    @staticmethod
    def get_recent_failures_by_email(email, minutes=15):
        """Get failed attempts for an email in the last N minutes"""
        from datetime import timedelta
        cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)
        
        return VerificationAttempt.query.filter(
            VerificationAttempt.email == email,
            VerificationAttempt.success == False,
            VerificationAttempt.created_at >= cutoff_time
        ).count()
    
    @staticmethod
    def get_recent_failures_by_ip(ip_address, minutes=15):
        """Get failed attempts from an IP in the last N minutes"""
        from datetime import timedelta
        cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)
        
        return VerificationAttempt.query.filter(
            VerificationAttempt.ip_address == ip_address,
            VerificationAttempt.success == False,
            VerificationAttempt.created_at >= cutoff_time
        ).count()
    
    @staticmethod
    def is_rate_limited(email, ip_address, max_attempts=5, window_minutes=15):
        """Check if email or IP is rate limited"""
        email_failures = VerificationAttempt.get_recent_failures_by_email(email, window_minutes)
        ip_failures = VerificationAttempt.get_recent_failures_by_ip(ip_address, window_minutes)
        
        return email_failures >= max_attempts or ip_failures >= max_attempts
    
    @staticmethod
    def get_suspicious_activity(hours=24, threshold=10):
        """Get emails or IPs with suspicious activity (many failures)"""
        from datetime import timedelta
        from sqlalchemy import func
        
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        # Get suspicious emails
        suspicious_emails = db.session.query(
            VerificationAttempt.email,
            func.count(VerificationAttempt.id).label('failure_count')
        ).filter(
            VerificationAttempt.success == False,
            VerificationAttempt.created_at >= cutoff_time
        ).group_by(
            VerificationAttempt.email
        ).having(
            func.count(VerificationAttempt.id) >= threshold
        ).all()
        
        # Get suspicious IPs
        suspicious_ips = db.session.query(
            VerificationAttempt.ip_address,
            func.count(VerificationAttempt.id).label('failure_count')
        ).filter(
            VerificationAttempt.success == False,
            VerificationAttempt.created_at >= cutoff_time,
            VerificationAttempt.ip_address.isnot(None)
        ).group_by(
            VerificationAttempt.ip_address
        ).having(
            func.count(VerificationAttempt.id) >= threshold
        ).all()
        
        return {
            'emails': [{'email': e[0], 'failures': e[1]} for e in suspicious_emails],
            'ips': [{'ip': ip[0], 'failures': ip[1]} for ip in suspicious_ips]
        }

