"""
Input validation utilities
"""
import re
from email_validator import validate_email, EmailNotValidError


def validate_email_format(email):
    """Validate email format"""
    try:
        valid = validate_email(email)
        return True, valid.email
    except EmailNotValidError as e:
        return False, str(e)


def validate_password_strength(password):
    """
    Validate password strength
    Requirements:
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    - Special characters are recommended, not required
    """
    if len(password) < 8:
        return False, 'Password must be at least 8 characters long'
    
    if not re.search(r'[A-Z]', password):
        return False, 'Password must contain at least one uppercase letter'
    
    if not re.search(r'[a-z]', password):
        return False, 'Password must contain at least one lowercase letter'
    
    if not re.search(r'\d', password):
        return False, 'Password must contain at least one number'
    
    return True, 'Password is strong'


def validate_phone_number(phone):
    """Validate phone number format (basic)"""
    # Remove spaces and dashes
    phone = re.sub(r'[\s\-]', '', phone)
    
    # Check if it's a valid format (10-15 digits, may start with +)
    if re.match(r'^\+?\d{10,15}$', phone):
        return True, phone
    
    return False, 'Invalid phone number format'


def validate_required_fields(data, required_fields):
    """Validate that required fields are present"""
    missing_fields = []
    
    for field in required_fields:
        if field not in data or not data[field]:
            missing_fields.append(field)
    
    if missing_fields:
        return False, f"Missing required fields: {', '.join(missing_fields)}"
    
    return True, 'All required fields present'


def sanitize_string(text, max_length=None):
    """Sanitize string input"""
    if not text:
        return text
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    # Limit length if specified
    if max_length and len(text) > max_length:
        text = text[:max_length]
    
    return text



def validate_integer(value, min_value=None, max_value=None):
    """Validate that a value is an integer and within a range"""
    if not isinstance(value, int):
        return False, 'Value must be an integer'
    
    if min_value is not None and value < min_value:
        return False, f'Value must be at least {min_value}'
    
    if max_value is not None and value > max_value:
        return False, f'Value must be at most {max_value}'
    
    return True, 'Value is a valid integer'

def validate_float(value, min_value=None, max_value=None):
    """Validate that a value is a float and within a range"""
    if not isinstance(value, float):
        return False, 'Value must be a float'
    
    if min_value is not None and value < min_value:
        return False, f'Value must be at least {min_value}'
    
    if max_value is not None and value > max_value:
        return False, f'Value must be at most {max_value}'
    
    return True, 'Value is a valid float'

def validate_boolean(value):
    """Validate that a value is a boolean"""
    if not isinstance(value, bool):
        return False, 'Value must be a boolean'
    
    return True, 'Value is a valid boolean'

def validate_choice(value, choices):
    """Validate that a value is one of the allowed choices"""
    if value not in choices:
        return False, f"Invalid choice. Must be one of: {', '.join(str(c) for c in choices)}"
    
    return True, 'Value is a valid choice'



def validate_string(text, min_length=None, max_length=None, exact_length=None):
    """Validate string input"""
    if not text:
        return False, 'String cannot be empty'
    
    text = text.strip()
    
    if min_length and len(text) < min_length:
        return False, f'String must be at least {min_length} characters long'
    
    if max_length and len(text) > max_length:
        return False, f'String must be at most {max_length} characters long'
    
    if exact_length and len(text) != exact_length:
        return False, f'String must be exactly {exact_length} characters long'
    
    return True, text




def validate_string(text, min_length=None, max_length=None, exact_length=None):
    """Validate string input"""
    if not text:
        return False, 'String cannot be empty'
    
    text = text.strip()
    
    if min_length and len(text) < min_length:
        return False, f'String must be at least {min_length} characters long'
    
    if max_length and len(text) > max_length:
        return False, f'String must be at most {max_length} characters long'
    
    if exact_length and len(text) != exact_length:
        return False, f'String must be exactly {exact_length} characters long'
    
    return True, text

def validate_phone_number(phone):
    """Basic phone number validation"""
    if not phone:
        return True, None # Phone number is optional
    
    phone = phone.strip()
    if not (8 <= len(phone) <= 20):
        return False, 'Invalid phone number'
        
    return True, phone

