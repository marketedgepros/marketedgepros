"""
HashiCorp Vault client for MarketEdgePros
Securely retrieve secrets from Vault instead of .env
"""

import hvac
import os
from functools import lru_cache

class VaultClient:
    def __init__(self):
        self.vault_addr = os.getenv('VAULT_ADDR', 'http://127.0.0.1:8200')
        self.vault_token = os.getenv('VAULT_TOKEN')
        self.vault_mount = os.getenv('VAULT_MOUNT', 'marketedgepros')
        
        if not self.vault_token:
            raise ValueError('VAULT_TOKEN environment variable is required')
        
        self.client = hvac.Client(
            url=self.vault_addr,
            token=self.vault_token
        )
        
        if not self.client.is_authenticated():
            raise ValueError('Vault authentication failed')
    
    @lru_cache(maxsize=128)
    def get_secret(self, path):
        """
        Get a secret from Vault
        
        Args:
            path: Relative secret path (e.g., 'flask')
        
        Returns:
            dict: Secret data
        """
        try:
            response = self.client.secrets.kv.v2.read_secret_version(
                path=path.lstrip('/'),
                mount_point=self.vault_mount
            )
            return response['data']['data']
        except Exception as e:
            raise ValueError(f'Failed to retrieve secret from {path}: {e}')
    
    def get_flask_secrets(self):
        """Get Flask configuration secrets"""
        return self.get_secret('flask')
    
    def get_database_url(self):
        """Get database connection URL"""
        secrets = self.get_secret('database')
        return secrets['DATABASE_URL']
    
    def get_sendgrid_config(self):
        """Get SendGrid configuration"""
        return self.get_secret('sendgrid')
    
    def get_nowpayments_config(self):
        """Get NowPayments configuration"""
        return self.get_secret('nowpayments')

# Singleton instance
_vault_client = None

def get_vault_client():
    """Get or create Vault client instance"""
    global _vault_client
    if _vault_client is None:
        _vault_client = VaultClient()
    return _vault_client

# Usage in app.py:
"""
from src.utils.vault_client import get_vault_client

# Get Vault client
vault = get_vault_client()

# Load secrets
flask_secrets = vault.get_flask_secrets()
app.config['SECRET_KEY'] = flask_secrets['SECRET_KEY']
app.config['JWT_SECRET_KEY'] = flask_secrets['JWT_SECRET_KEY']

app.config['SQLALCHEMY_DATABASE_URI'] = vault.get_database_url()

sendgrid_config = vault.get_sendgrid_config()
app.config['SENDGRID_API_KEY'] = sendgrid_config['API_KEY']
app.config['SENDGRID_FROM_EMAIL'] = sendgrid_config['FROM_EMAIL']

nowpayments_config = vault.get_nowpayments_config()
app.config['NOWPAYMENTS_API_KEY'] = nowpayments_config['API_KEY']
"""
