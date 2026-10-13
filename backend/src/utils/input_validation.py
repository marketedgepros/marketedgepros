"""
Input Validation and Sanitization
Prevents SQL injection, XSS, and other injection attacks
"""
import re
import bleach
import validators
from typing import Optional, Union

class InputValidator:
    """Validate and sanitize user inputs"""
    
    # Password requirements
    PASSWORD_MIN_LENGTH = 8
    PASSWORD_MAX_LENGTH = 128
    PASSWORD_REQUIRE_UPPERCASE = True
    PASSWORD_REQUIRE_LOWERCASE = True
    PASSWORD_REQUIRE_DIGIT = True
    PASSWORD_REQUIRE_SPECIAL = False  # Recommended, not required by the approved policy
    
    # Allowed HTML tags for rich text (if needed)
    ALLOWED_HTML_TAGS = ['p', 'br', 'strong', 'em', 'u', 'a', 'ul', 'ol', 'li']
    ALLOWED_HTML_ATTRIBUTES = {'a': ['href', 'title']}
    
    @staticmethod
    def sanitize_string(text: str, allow_html: bool = False) -> str:
        """
        Sanitize string input to prevent XSS
        
        Args:
            text: Input string
            allow_html: Whether to allow safe HTML tags
            
        Returns:
            Sanitized string
        """
        if not text:
            return ''
        
        # Convert to string if not already
        text = str(text).strip()
        
        if allow_html:
            # Allow safe HTML tags
            return bleach.clean(
                text,
                tags=InputValidator.ALLOWED_HTML_TAGS,
                attributes=InputValidator.ALLOWED_HTML_ATTRIBUTES,
                strip=True
            )
        else:
            # Strip all HTML tags
            return bleach.clean(text, tags=[], strip=True)
    
    @staticmethod
    def validate_email(email: str) -> tuple[bool, Optional[str]]:
        """
        Validate email address
        
        Returns:
            (is_valid, error_message)
        """
        if not email:
            return False, 'Email is required'
        
        email = email.strip().lower()
        
        # Check length
        if len(email) > 254:
            return False, 'Email is too long'
        
        # Validate format
        if not validators.email(email):
            return False, 'Invalid email format'
        
        # Additional checks
        if '..' in email:
            return False, 'Email contains consecutive dots'
        
        if email.startswith('.') or email.endswith('.'):
            return False, 'Email cannot start or end with a dot'
        
        return True, None
    
    @staticmethod
    def validate_password(password: str) -> tuple[bool, Optional[str]]:
        """
        Validate password strength
        
        Returns:
            (is_valid, error_message)
        """
        if not password:
            return False, 'Password is required'
        
        # Check length
        if len(password) < InputValidator.PASSWORD_MIN_LENGTH:
            return False, f'Password must be at least {InputValidator.PASSWORD_MIN_LENGTH} characters'
        
        if len(password) > InputValidator.PASSWORD_MAX_LENGTH:
            return False, f'Password must not exceed {InputValidator.PASSWORD_MAX_LENGTH} characters'
        
        # Check complexity
        if InputValidator.PASSWORD_REQUIRE_UPPERCASE and not re.search(r'[A-Z]', password):
            return False, 'Password must contain at least one uppercase letter'
        
        if InputValidator.PASSWORD_REQUIRE_LOWERCASE and not re.search(r'[a-z]', password):
            return False, 'Password must contain at least one lowercase letter'
        
        if InputValidator.PASSWORD_REQUIRE_DIGIT and not re.search(r'[0-9]', password):
            return False, 'Password must contain at least one digit'
        
        if InputValidator.PASSWORD_REQUIRE_SPECIAL and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            return False, 'Password must contain at least one special character'
        
        # Check for common weak passwords
        weak_passwords = ['password', '12345678', 'qwerty', 'abc123', 'password123']
        if password.lower() in weak_passwords:
            return False, 'Password is too common'
        
        return True, None
    
    @staticmethod
    def validate_username(username: str) -> tuple[bool, Optional[str]]:
        """
        Validate username
        
        Returns:
            (is_valid, error_message)
        """
        if not username:
            return False, 'Username is required'
        
        username = username.strip()
        
        # Check length
        if len(username) < 3:
            return False, 'Username must be at least 3 characters'
        
        if len(username) > 30:
            return False, 'Username must not exceed 30 characters'
        
        # Check format (alphanumeric, underscore, hyphen only)
        if not re.match(r'^[a-zA-Z0-9_-]+$', username):
            return False, 'Username can only contain letters, numbers, underscores, and hyphens'
        
        # Cannot start with number
        if username[0].isdigit():
            return False, 'Username cannot start with a number'
        
        return True, None
    
    @staticmethod
    def validate_phone(phone: str) -> tuple[bool, Optional[str]]:
        """
        Validate phone number
        
        Returns:
            (is_valid, error_message)
        """
        if not phone:
            return False, 'Phone number is required'
        
        # Remove common formatting characters
        phone_digits = re.sub(r'[\s\-\(\)\+]', '', phone)
        
        # Check if only digits remain
        if not phone_digits.isdigit():
            return False, 'Phone number can only contain digits'
        
        # Check length (international format)
        if len(phone_digits) < 10 or len(phone_digits) > 15:
            return False, 'Phone number must be between 10 and 15 digits'
        
        return True, None
    
    @staticmethod
    def validate_url(url: str) -> tuple[bool, Optional[str]]:
        """
        Validate URL
        
        Returns:
            (is_valid, error_message)
        """
        if not url:
            return False, 'URL is required'
        
        url = url.strip()
        
        # Validate format
        if not validators.url(url):
            return False, 'Invalid URL format'
        
        # Check protocol
        if not url.startswith(('http://', 'https://')):
            return False, 'URL must start with http:// or https://'
        
        return True, None
    
    @staticmethod
    def validate_amount(amount: Union[int, float, str]) -> tuple[bool, Optional[str]]:
        """
        Validate monetary amount
        
        Returns:
            (is_valid, error_message)
        """
        try:
            amount_float = float(amount)
        except (ValueError, TypeError):
            return False, 'Amount must be a number'
        
        # Check if positive
        if amount_float <= 0:
            return False, 'Amount must be greater than zero'
        
        # Check if reasonable (prevent overflow)
        if amount_float > 1000000000:  # 1 billion
            return False, 'Amount is too large'
        
        # Check decimal places (max 2 for currency)
        if round(amount_float, 2) != amount_float:
            return False, 'Amount can have at most 2 decimal places'
        
        return True, None
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Sanitize filename to prevent directory traversal
        
        Returns:
            Safe filename
        """
        if not filename:
            return 'unnamed'
        
        # Remove path separators
        filename = filename.replace('/', '_').replace('\\', '_')
        
        # Remove null bytes
        filename = filename.replace('\x00', '')
        
        # Remove leading/trailing dots and spaces
        filename = filename.strip('. ')
        
        # Allow only safe characters
        filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
        
        # Limit length
        if len(filename) > 255:
            name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
            filename = name[:250] + ('.' + ext if ext else '')
        
        return filename or 'unnamed'
    
    @staticmethod
    def detect_sql_injection(text: str) -> bool:
        """
        Detect potential SQL injection attempts
        
        Returns:
            True if SQL injection detected
        """
        if not text:
            return False
        
        text_lower = text.lower()
        
        # Common SQL injection patterns
        sql_patterns = [
            r'(\b(select|insert|update|delete|drop|create|alter|exec|execute)\b.*\b(from|into|table|database)\b)',
            r'(union\s+select)',
            r'(\bor\b.*=.*)',
            r'(;\s*(drop|delete|update))',
            r'(--)',
            r'(/\*.*\*/)',
            r'(xp_cmdshell)',
            r'(\bexec\s*\()',
        ]
        
        for pattern in sql_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        
        return False
    
    @staticmethod
    def detect_xss(text: str) -> bool:
        """
        Detect potential XSS attempts
        
        Returns:
            True if XSS detected
        """
        if not text:
            return False
        
        text_lower = text.lower()
        
        # Common XSS patterns
        xss_patterns = [
            r'<script',
            r'javascript:',
            r'onerror\s*=',
            r'onload\s*=',
            r'onclick\s*=',
            r'<iframe',
            r'<embed',
            r'<object',
        ]
        
        for pattern in xss_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        
        return False

# Convenience function for quick validation
def validate_input(value: str, input_type: str) -> tuple[bool, Optional[str]]:
    """
    Validate input based on type
    
    Args:
        value: Input value
        input_type: Type of input (email, password, username, phone, url, amount)
        
    Returns:
        (is_valid, error_message)
    """
    validators_map = {
        'email': InputValidator.validate_email,
        'password': InputValidator.validate_password,
        'username': InputValidator.validate_username,
        'phone': InputValidator.validate_phone,
        'url': InputValidator.validate_url,
        'amount': InputValidator.validate_amount,
    }
    
    validator = validators_map.get(input_type)
    if not validator:
        return False, f'Unknown input type: {input_type}'
    
    return validator(value)
