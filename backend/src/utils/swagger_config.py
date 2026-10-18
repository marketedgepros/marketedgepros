"""
Swagger/OpenAPI configuration for MarketEdgePros API
Add this to app.py after app creation
"""

from flasgger import Swagger

def init_swagger(app):
    """Initialize Swagger UI for API documentation"""
    
    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": 'apispec',
                "route": '/apispec.json',
                "rule_filter": lambda rule: True,  # all in
                "model_filter": lambda tag: True,  # all in
            }
        ],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/api/docs"
    }
    
    swagger_template = {
        "swagger": "2.0",
        "info": {
            "title": "MarketEdgePros API",
            "description": "Professional Trading Challenge Platform API Documentation",
            "contact": {
                "url": "https://marketedgepros.com"
            },
            "version": "1.0.0"
        },
        "host": "marketedgepros.com",
        "basePath": "/api",
        "schemes": [
            "https",
            "http"
        ],
        "securityDefinitions": {
            "Bearer": {
                "type": "apiKey",
                "name": "Authorization",
                "in": "header",
                "description": "JWT Authorization header using the Bearer scheme. Example: 'Bearer {token}'"
            }
        },
        "security": [
            {
                "Bearer": []
            }
        ],
        "tags": [
            {
                "name": "Authentication",
                "description": "User authentication and registration"
            },
            {
                "name": "Challenges",
                "description": "Trading challenge management"
            },
            {
                "name": "Users",
                "description": "User management"
            },
            {
                "name": "Admin",
                "description": "Administrative operations"
            },
            {
                "name": "Payments",
                "description": "Payment processing"
            },
            {
                "name": "Reports",
                "description": "Analytics and reporting"
            }
        ]
    }
    
    Swagger(app, config=swagger_config, template=swagger_template)
    
    app.logger.info('Swagger UI initialized at /api/docs')

# Usage in app.py:
# from src.utils.swagger_config import init_swagger
# init_swagger(app)

# Example endpoint documentation:
"""
@app.route('/api/challenges', methods=['GET'])
def get_challenges():
    '''
    Get all challenges
    ---
    tags:
      - Challenges
    security:
      - Bearer: []
    parameters:
      - name: status
        in: query
        type: string
        enum: [pending, active, passed, failed]
        description: Filter by challenge status
      - name: page
        in: query
        type: integer
        default: 1
        description: Page number
      - name: per_page
        in: query
        type: integer
        default: 10
        description: Items per page
    responses:
      200:
        description: List of challenges
        schema:
          type: object
          properties:
            challenges:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  user_id:
                    type: integer
                  program_id:
                    type: integer
                  status:
                    type: string
                  balance:
                    type: number
                  equity:
                    type: number
                  created_at:
                    type: string
                    format: date-time
            total:
              type: integer
            page:
              type: integer
            pages:
              type: integer
      401:
        description: Unauthorized
      500:
        description: Internal server error
    '''
    # Your endpoint code here
    pass
"""
