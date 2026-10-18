"""
Notification Service
Send alerts via email, Slack, SMS for monitoring events
"""

import os
import requests
import logging
from datetime import datetime
from flask_mail import Mail, Message
from twilio.rest import Client

logger = logging.getLogger(__name__)


class NotificationService:
    """Handle all notification channels"""
    
    def __init__(self, app=None):
        self.app = app
        self.mail = None
        self.twilio_client = None
        self.slack_webhook_url = None
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize with Flask app"""
        self.app = app
        
        # Initialize Flask-Mail
        self.mail = Mail(app)
        
        # Initialize Twilio
        twilio_sid = app.config.get('TWILIO_ACCOUNT_SID')
        twilio_token = app.config.get('TWILIO_AUTH_TOKEN')
        if twilio_sid and twilio_token:
            self.twilio_client = Client(twilio_sid, twilio_token)
        
        # Slack webhook
        self.slack_webhook_url = app.config.get('SLACK_WEBHOOK_URL')
    
    def send_violation_email(self, user, challenge, violations):
        """Send violation notification email to user"""
        try:
            if not self.mail:
                logger.warning("Mail not configured")
                return False
            
            # Build email content
            subject = f"Challenge Violation - Account {challenge.account_number}"
            
            violation_details = "\n".join([
                f"- {v['type']}: {v['message']}" for v in violations
            ])
            
            body = f"""
Dear {user.email},

We regret to inform you that your trading challenge (Account: {challenge.account_number}) has been terminated due to a rule violation.

Violation Details:
{violation_details}

Your MT5 account has been disabled automatically.

If you believe this is an error, please contact support immediately.

Best regards,
MarketEdgePros Team
            """
            
            # Send email
            msg = Message(
                subject=subject,
                recipients=[user.email],
                body=body
            )
            
            self.mail.send(msg)
            logger.info(f"Violation email sent to {user.email}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending violation email: {str(e)}")
            return False
    
    def send_admin_alert(self, challenge, violations):
        """Send alert email to admins"""
        try:
            if not self.mail:
                logger.warning("Mail not configured")
                return False
            
            admin_email = self.app.config.get('ADMIN_EMAIL') if self.app else None
            if not admin_email:
                logger.warning('ADMIN_EMAIL not configured; skipping admin alert')
                return False

            
            # Build email content
            subject = f"🚨 Challenge Violation Alert - ID {challenge.id}"
            
            violation_details = "\n".join([
                f"- {v['type']}: {v['message']}" for v in violations
            ])
            
            daily_stats = challenge.get_daily_stats()
            
            body = f"""
VIOLATION ALERT

Challenge ID: {challenge.id}
User: {challenge.user.email if challenge.user else 'Unknown'}
Account: {challenge.account_number}
Program: {challenge.program.name if challenge.program else 'Unknown'}

Violations:
{violation_details}

Current Stats:
- Balance: ${daily_stats.get('current_balance', 0):,.2f}
- Equity: ${daily_stats.get('current_equity', 0):,.2f}
- Daily P/L: ${daily_stats.get('daily_pnl', 0):,.2f} ({daily_stats.get('daily_pnl_pct', 0):.2f}%)
- Threshold: ${daily_stats.get('threshold', 0):,.2f}
- Remaining Room: ${daily_stats.get('remaining_room', 0):,.2f}

Action Taken: MT5 account disabled automatically

Time: {datetime.utcnow().isoformat()}
            """
            
            # Send email
            msg = Message(
                subject=subject,
                recipients=[admin_email],
                body=body
            )
            
            self.mail.send(msg)
            logger.info(f"Admin alert sent to {admin_email}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending admin alert: {str(e)}")
            return False
    
    def send_slack_alert(self, challenge, violations):
        """Send alert to Slack"""
        try:
            if not self.slack_webhook_url:
                logger.warning("Slack webhook not configured")
                return False
            
            daily_stats = challenge.get_daily_stats()
            
            # Build Slack message
            violation_text = "\n".join([
                f"• *{v['type']}*: {v['message']}" for v in violations
            ])
            
            payload = {
                "text": "🚨 Challenge Violation Alert",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "🚨 Challenge Violation Alert"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Challenge ID:*\n{challenge.id}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*User:*\n{challenge.user.email if challenge.user else 'Unknown'}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Account:*\n{challenge.account_number}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Program:*\n{challenge.program.name if challenge.program else 'Unknown'}"
                            }
                        ]
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Violations:*\n{violation_text}"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Balance:*\n${daily_stats.get('current_balance', 0):,.2f}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Equity:*\n${daily_stats.get('current_equity', 0):,.2f}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Daily P/L:*\n${daily_stats.get('daily_pnl', 0):,.2f} ({daily_stats.get('daily_pnl_pct', 0):.2f}%)"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Remaining Room:*\n${daily_stats.get('remaining_room', 0):,.2f}"
                            }
                        ]
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Action:* MT5 account disabled automatically\n*Time:* {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
                        }
                    }
                ]
            }
            
            # Send to Slack
            response = requests.post(self.slack_webhook_url, json=payload)
            
            if response.status_code == 200:
                logger.info("Slack alert sent successfully")
                return True
            else:
                logger.error(f"Slack alert failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending Slack alert: {str(e)}")
            return False
    
    def send_sms_alert(self, phone_number, message):
        """Send SMS alert (for critical violations only)"""
        try:
            if not self.twilio_client:
                logger.warning("Twilio not configured")
                return False
            
            from_number = self.app.config.get('TWILIO_PHONE_NUMBER')
            
            message = self.twilio_client.messages.create(
                body=message,
                from_=from_number,
                to=phone_number
            )
            
            logger.info(f"SMS sent to {phone_number}: {message.sid}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending SMS: {str(e)}")
            return False
    
    @staticmethod
    def create_notification(user_id, notification_type, title, message, metadata=None):
        """Create a notification for a user
        
        Args:
            user_id: ID of the user to notify
            notification_type: Type of notification (commission, payment, withdrawal, etc.)
            title: Notification title
            message: Notification message
            metadata: Optional JSON metadata
            
        Returns:
            Notification object if created, None otherwise
        """
        try:
            from src.models import Notification
            from src.database import db
            
            notification = Notification(
                user_id=user_id,
                notification_type=notification_type,
                title=title,
                message=message,
                metadata=metadata
            )
            
            db.session.add(notification)
            db.session.commit()
            
            logger.info(f"Notification created for user {user_id}: {title}")
            return notification
            
        except Exception as e:
            logger.error(f"Error creating notification: {str(e)}")
            db.session.rollback()
            return None
    
    def send_approaching_limit_warning(self, challenge, usage_pct):
        """Send warning when approaching limit (80%+)"""
        try:
            user = challenge.user
            if not user:
                return False
            
            subject = f"⚠️ Warning: Approaching Daily Limit - Account {challenge.account_number}"
            
            daily_stats = challenge.get_daily_stats()
            
            body = f"""
Dear {user.email},

This is a warning that your trading challenge (Account: {challenge.account_number}) is approaching the daily loss limit.

Current Status:
- Daily Limit Usage: {usage_pct:.1f}%
- Balance: ${daily_stats.get('current_balance', 0):,.2f}
- Equity: ${daily_stats.get('current_equity', 0):,.2f}
- Daily P/L: ${daily_stats.get('daily_pnl', 0):,.2f} ({daily_stats.get('daily_pnl_pct', 0):.2f}%)
- Remaining Room: ${daily_stats.get('remaining_room', 0):,.2f}
- Threshold: ${daily_stats.get('threshold', 0):,.2f}

Please manage your risk carefully to avoid violating the daily loss limit.

Best regards,
MarketEdgePros Team
            """
            
            msg = Message(
                subject=subject,
                recipients=[user.email],
                body=body
            )
            
            self.mail.send(msg)
            logger.info(f"Warning email sent to {user.email}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending warning email: {str(e)}")
            return False


# Configuration example for .env:
"""
# Email (Flask-Mail)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
MAIL_DEFAULT_SENDER=your-verified-sender@example.com
ADMIN_EMAIL=your-admin-email@example.com

# Twilio (SMS)
TWILIO_ACCOUNT_SID=your-twilio-sid
TWILIO_AUTH_TOKEN=your-twilio-token
TWILIO_PHONE_NUMBER=+1234567890

# Slack
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
"""
