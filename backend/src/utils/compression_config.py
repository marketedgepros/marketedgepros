"""
Response compression configuration for MarketEdgePros
Compress API responses to reduce bandwidth and improve speed
"""

from flask_compress import Compress

def init_compression(app):
    """Initialize response compression"""
    
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html',
        'text/css',
        'text/xml',
        'application/json',
        'application/javascript',
        'text/javascript',
    ]
    
    app.config['COMPRESS_LEVEL'] = 6  # Compression level (1-9, 6 is good balance)
    app.config['COMPRESS_MIN_SIZE'] = 500  # Only compress responses > 500 bytes
    app.config['COMPRESS_ALGORITHM'] = 'br'  # Use Brotli (better than gzip)
    
    compress = Compress(app)
    
    app.logger.info('Response compression initialized (Brotli)')
    
    return compress

# Usage in app.py:
"""
from src.utils.compression_config import init_compression

compress = init_compression(app)
"""

# Compression will automatically apply to all responses!
# No need to change route code.

# Benefits:
# - JSON responses: 70-80% smaller
# - HTML responses: 60-70% smaller
# - Faster page loads
# - Less bandwidth usage
