from src.database import db
from datetime import datetime

class SupportTicket(db.Model):
    __tablename__ = 'support_tickets'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(20), unique=True, nullable=False)  # e.g., TICKET-001234
    
    # User info
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Nullable for guest tickets
    email = db.Column(db.String(255), nullable=False)  # Email for guest users
    name = db.Column(db.String(200), nullable=False)  # Name for guest users
    
    # Ticket details
    subject = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False)  # technical, billing, account, general, kyc, withdrawal
    priority = db.Column(db.String(20), default='medium')  # low, medium, high, urgent
    status = db.Column(db.String(20), default='open')  # open, in_progress, waiting_customer, resolved, closed
    
    # Assignment
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Attachments (JSON array of file URLs)
    attachments = db.Column(db.Text, nullable=True)  # JSON string: ["url1", "url2"]
    
    # Tracking
    first_response_at = db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    
    # Ratings
    rating = db.Column(db.Integer, nullable=True)  # 1-5 stars
    feedback = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref='support_tickets')
    assigned_user = db.relationship('User', foreign_keys=[assigned_to], backref='assigned_tickets')
    messages = db.relationship('TicketMessage', backref='ticket', lazy='dynamic', cascade='all, delete-orphan')
    
    def to_dict(self, include_messages=False):
        """Convert ticket to dictionary"""
        import json
        
        data = {
            'id': self.id,
            'ticket_number': self.ticket_number,
            'user_id': self.user_id,
            'email': self.email,
            'name': self.name,
            'subject': self.subject,
            'description': self.description,
            'category': self.category,
            'priority': self.priority,
            'status': self.status,
            'assigned_to': self.assigned_to,
            'attachments': json.loads(self.attachments) if self.attachments else [],
            'first_response_at': self.first_response_at.isoformat() if self.first_response_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'rating': self.rating,
            'feedback': self.feedback,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
        
        # Include user info if available
        if self.user:
            data['user'] = {
                'id': self.user.id,
                'email': self.user.email,
                'first_name': self.user.first_name,
                'last_name': self.user.last_name
            }
        
        # Include assigned user info if available
        if self.assigned_user:
            data['assigned_user'] = {
                'id': self.assigned_user.id,
                'email': self.assigned_user.email,
                'first_name': self.assigned_user.first_name,
                'last_name': self.assigned_user.last_name
            }
        
        # Include messages if requested
        if include_messages:
            data['messages'] = [msg.to_dict() for msg in self.messages.order_by(TicketMessage.created_at.asc())]
            data['message_count'] = self.messages.count()
        else:
            data['message_count'] = self.messages.count()
            data['last_message'] = self.messages.order_by(TicketMessage.created_at.desc()).first().to_dict() if self.messages.count() > 0 else None
        
        return data
    
    @staticmethod
    def generate_ticket_number():
        """Return one URL-safe candidate; the database unique index resolves races.

        Allocation retries belong to the write transaction so this method never
        loops or performs a racy preflight query.  Eight bytes provide 64 bits of
        entropy while the ``TICKET-`` prefix keeps the persisted value under the
        existing 20-character column limit.
        """
        import secrets

        return 'TICKET-' + secrets.token_urlsafe(8).rstrip('=')


class TicketMessage(db.Model):
    __tablename__ = 'ticket_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('support_tickets.id'), nullable=False)
    
    # Message details
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Nullable for guest messages
    email = db.Column(db.String(255), nullable=True)  # Email for guest users
    name = db.Column(db.String(200), nullable=True)  # Name for guest users
    message = db.Column(db.Text, nullable=False)
    is_staff = db.Column(db.Boolean, default=False)  # True if message from support staff
    is_internal = db.Column(db.Boolean, default=False)  # True for internal notes (not visible to customer)
    
    # Attachments (JSON array of file URLs)
    attachments = db.Column(db.Text, nullable=True)  # JSON string: ["url1", "url2"]
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user = db.relationship('User', backref='ticket_messages')
    
    def to_dict(self):
        """Convert message to dictionary"""
        import json
        
        data = {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'user_id': self.user_id,
            'email': self.email,
            'name': self.name,
            'message': self.message,
            'is_staff': self.is_staff,
            'is_internal': self.is_internal,
            'attachments': json.loads(self.attachments) if self.attachments else [],
            'created_at': self.created_at.isoformat()
        }
        
        # Include user info if available
        if self.user:
            data['user'] = {
                'id': self.user.id,
                'email': self.user.email,
                'first_name': self.user.first_name,
                'last_name': self.user.last_name
            }
        
        return data


class FAQ(db.Model):
    __tablename__ = 'faqs'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Content
    question = db.Column(db.String(500), nullable=False)
    answer = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False)  # getting_started, account, trading, payments, technical
    
    # Display
    order = db.Column(db.Integer, default=0)  # For sorting
    is_featured = db.Column(db.Boolean, default=False)
    is_published = db.Column(db.Boolean, default=True)
    
    # Tracking
    view_count = db.Column(db.Integer, default=0)
    helpful_count = db.Column(db.Integer, default=0)
    not_helpful_count = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def to_dict(self):
        """Convert FAQ to dictionary"""
        return {
            'id': self.id,
            'question': self.question,
            'answer': self.answer,
            'category': self.category,
            'order': self.order,
            'is_featured': self.is_featured,
            'is_published': self.is_published,
            'view_count': self.view_count,
            'helpful_count': self.helpful_count,
            'not_helpful_count': self.not_helpful_count,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
