"""
Error messages for the MarketEdgePros platform
Bilingual error messages (English and Hebrew)
"""

ERROR_MESSAGES = {
    # User Creation Errors
    'MISSING_REQUIRED_FIELDS': {
        'en': 'Missing required fields: {fields}',
        'he': 'שדות חובה חסרים: {fields}',
        'code': 'ERR_001'
    },
    'INVALID_EMAIL_FORMAT': {
        'en': 'Invalid email format: {email}',
        'he': 'פורמט אימייל לא תקין: {email}',
        'code': 'ERR_002'
    },
    'USER_ALREADY_EXISTS': {
        'en': 'A user with this email already exists',
        'he': 'משתמש עם אימייל זה כבר קיים במערכת',
        'code': 'ERR_003'
    },
    'PHONE_REQUIRED_FOR_ROLE': {
        'en': 'Phone number is required for {role} role. Only Super Master can create users without phone verification.',
        'he': 'מספר טלפון נדרש עבור תפקיד {role}. רק סופר מאסטר יכול ליצור משתמשים ללא אימות טלפון.',
        'code': 'ERR_004'
    },
    'VERIFICATION_REQUIRED': {
        'en': 'Email and phone verification are required for this role. Only Super Master can bypass verification.',
        'he': 'אימות אימייל וטלפון נדרשים עבור תפקיד זה. רק סופר מאסטר יכול לדלג על אימות.',
        'code': 'ERR_005'
    },
    'WEAK_PASSWORD': {
        'en': 'Password must be at least 8 characters and include uppercase, lowercase and number. A special character is recommended.',
        'he': 'הסיסמה חייבת להכיל לפחות 8 תווים, אות גדולה, אות קטנה ומספר. תו מיוחד מומלץ אך אינו חובה.',
        'code': 'ERR_006'
    },
    'INVALID_PHONE_FORMAT': {
        'en': 'Invalid phone number format. Expected format: XX-XXX-XXXX',
        'he': 'פורמט מספר טלפון לא תקין. פורמט נדרש: XX-XXX-XXXX',
        'code': 'ERR_007'
    },
    'INVALID_ROLE': {
        'en': 'Invalid role. Allowed roles: {roles}',
        'he': 'תפקיד לא תקין. תפקידים מותרים: {roles}',
        'code': 'ERR_008'
    },
    'CANNOT_CREATE_SAME_ROLE': {
        'en': 'You do not have permission to create another {role}. Only the root administrator can create users of the same role.',
        'he': 'אין לך הרשאה ליצור {role} נוסף. רק מנהל הראשי יכול ליצור משתמשים באותה דרגה.',
        'code': 'ERR_009'
    },
    
    # User Update Errors
    'USER_NOT_FOUND': {
        'en': 'User not found',
        'he': 'משתמש לא נמצא',
        'code': 'ERR_101'
    },
    'CANNOT_MODIFY_SUPERMASTER': {
        'en': 'Cannot modify Super Master account',
        'he': 'לא ניתן לשנות חשבון סופר מאסטר',
        'code': 'ERR_102'
    },
    'INSUFFICIENT_PERMISSIONS': {
        'en': 'You do not have permission to perform this action',
        'he': 'אין לך הרשאה לבצע פעולה זו',
        'code': 'ERR_103'
    },
    
    # Authentication Errors
    'INVALID_CREDENTIALS': {
        'en': 'Invalid email or password',
        'he': 'אימייל או סיסמה שגויים',
        'code': 'ERR_201'
    },
    'ACCOUNT_INACTIVE': {
        'en': 'Your account has been deactivated. Please contact support.',
        'he': 'החשבון שלך הושבת. אנא פנה לתמיכה.',
        'code': 'ERR_202'
    },
    'TOKEN_EXPIRED': {
        'en': 'Your session has expired. Please login again.',
        'he': 'ההתחברות שלך פגה. אנא התחבר מחדש.',
        'code': 'ERR_203'
    },
    'UNAUTHORIZED': {
        'en': 'Unauthorized access. Please login.',
        'he': 'גישה לא מורשית. אנא התחבר.',
        'code': 'ERR_204'
    },
    
    # Referral Code Errors
    'INVALID_REFERRAL_CODE': {
        'en': 'Invalid or expired referral code',
        'he': 'קוד הפניה לא תקין או פג תוקף',
        'code': 'ERR_301'
    },
    'REFERRAL_CODE_ALREADY_USED': {
        'en': 'This referral code has already been used',
        'he': 'קוד הפניה זה כבר נוצל',
        'code': 'ERR_302'
    },
    'CANNOT_USE_OWN_REFERRAL': {
        'en': 'You cannot use your own referral code',
        'he': 'לא ניתן להשתמש בקוד ההפניה שלך',
        'code': 'ERR_303'
    },
    
    # Database Errors
    'DATABASE_ERROR': {
        'en': 'A database error occurred. Please try again later.',
        'he': 'אירעה שגיאת מסד נתונים. אנא נסה שוב מאוחר יותר.',
        'code': 'ERR_500'
    },
    'UNKNOWN_ERROR': {
        'en': 'An unexpected error occurred. Please contact support.',
        'he': 'אירעה שגיאה לא צפויה. אנא פנה לתמיכה.',
        'code': 'ERR_999'
    }
}

def get_error_message(error_key, lang='en', **kwargs):
    """
    Get error message in specified language with optional parameters
    
    Args:
        error_key: Key from ERROR_MESSAGES dict
        lang: Language code ('en' or 'he')
        **kwargs: Parameters to format into the message
    
    Returns:
        dict with 'message', 'code', and 'lang'
    """
    if error_key not in ERROR_MESSAGES:
        error_key = 'UNKNOWN_ERROR'
    
    error_data = ERROR_MESSAGES[error_key]
    message = error_data[lang].format(**kwargs) if kwargs else error_data[lang]
    
    return {
        'message': message,
        'message_en': error_data['en'].format(**kwargs) if kwargs else error_data['en'],
        'message_he': error_data['he'].format(**kwargs) if kwargs else error_data['he'],
        'code': error_data['code'],
        'lang': lang
    }

def format_error_response(error_key, lang='en', **kwargs):
    """
    Format error response for API - English only
    
    Returns:
        dict suitable for jsonify()
    """
    error_info = get_error_message(error_key, 'en', **kwargs)
    return {
        'error': error_info['message_en'],
        'error_code': error_info['code']
    }
