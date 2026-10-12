"""
Improved logging configuration for MarketEdgePros
Add this to app.py to replace the current logging.basicConfig()
"""

import logging
from logging.handlers import RotatingFileHandler
import os

def setup_logging(app):
    """Setup comprehensive logging to files and console"""
    
    # Create logs directory if it doesn't exist
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    
    # Set log level based on environment
    log_level = logging.DEBUG if app.config.get('ENV') == 'development' else logging.INFO
    
    # Format for logs
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # ===== Main Application Log =====
    app_handler = RotatingFileHandler(
        os.path.join(logs_dir, 'app.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=10
    )
    app_handler.setLevel(log_level)
    app_handler.setFormatter(formatter)
    
    # ===== Error Log (only errors and critical) =====
    error_handler = RotatingFileHandler(
        os.path.join(logs_dir, 'error.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=10
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    
    # ===== Access Log (HTTP requests) =====
    access_handler = RotatingFileHandler(
        os.path.join(logs_dir, 'access.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5
    )
    access_handler.setLevel(logging.INFO)
    access_formatter = logging.Formatter(
        '%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    access_handler.setFormatter(access_formatter)
    
    # ===== Console Handler (for development) =====
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    
    # Add handlers to Flask app logger
    app.logger.addHandler(app_handler)
    app.logger.addHandler(error_handler)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(log_level)
    
    # Add handlers to root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(app_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)
    root_logger.setLevel(log_level)
    
    # Setup access logging
    @app.before_request
    def log_request():
        """Log each request"""
        access_logger = logging.getLogger('access')
        access_logger.addHandler(access_handler)
        access_logger.setLevel(logging.INFO)
        
        from flask import request
        access_logger.info(
            f'{request.remote_addr} - {request.method} {request.path} - '
            f'User-Agent: {request.headers.get("User-Agent", "Unknown")}'
        )
    
    @app.after_request
    def log_response(response):
        """Log response status"""
        access_logger = logging.getLogger('access')
        access_logger.info(f'Response: {response.status_code}')
        return response
    
    # Log startup
    app.logger.info('='*50)
    app.logger.info('MarketEdgePros Backend Starting')
    app.logger.info(f'Environment: {app.config.get("ENV", "unknown")}')
    app.logger.info(f'Log Level: {logging.getLevelName(log_level)}')
    app.logger.info(f'Logs Directory: {logs_dir}')
    app.logger.info('='*50)
    
    return app

# Usage in app.py:
# Replace:
#   logging.basicConfig(...)
# With:
#   from src.utils.logging_config import setup_logging
#   setup_logging(app)
