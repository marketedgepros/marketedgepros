"""
Authentication Schemas
"""
from marshmallow import Schema, fields, validate, validates, ValidationError
import re


class RegisterSchema(Schema):
    """User registration schema"""
    email = fields.Email(required=True, error_messages={
        'required': 'Email is required',
        'invalid': 'Invalid email format'
    })
    password = fields.Str(
        required=True,
        validate=validate.Length(min=8, max=128),
        error_messages={'required': 'Password is required'}
    )
    first_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=100),
        error_messages={'required': 'First name is required'}
    )
    last_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=100),
        error_messages={'required': 'Last name is required'}
    )
    phone = fields.Str(
        validate=validate.Length(min=8, max=20),
        allow_none=True
    )
    country_code = fields.Str(
        validate=validate.Length(equal=2),
        allow_none=True
    )
    referral_code = fields.Str(
        validate=validate.Length(max=20),
        allow_none=True
    )
    tenant_id = fields.Int(allow_none=True)
    
    @validates('password')
    def validate_password(self, value):
        """Validate password strength"""
        if not re.search(r'[A-Z]', value):
            raise ValidationError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', value):
            raise ValidationError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', value):
            raise ValidationError('Password must contain at least one number')


class LoginSchema(Schema):
    """User login schema"""
    email = fields.Email(required=True, error_messages={
        'required': 'Email is required',
        'invalid': 'Invalid email format'
    })
    password = fields.Str(required=True, error_messages={
        'required': 'Password is required'
    })


class Login2FASchema(Schema):
    """2FA login schema"""
    email = fields.Email(required=True)
    code = fields.Str(
        required=True,
        validate=validate.Length(equal=6),
        error_messages={'required': '2FA code is required'}
    )
    
    @validates('code')
    def validate_code(self, value):
        """Validate 2FA code format"""
        if not value.isdigit():
            raise ValidationError('2FA code must be 6 digits')


class PasswordResetRequestSchema(Schema):
    """Password reset request schema"""
    email = fields.Email(required=True, error_messages={
        'required': 'Email is required',
        'invalid': 'Invalid email format'
    })


class PasswordResetSchema(Schema):
    """Password reset with code schema"""
    email = fields.Email(required=True)
    code = fields.Str(
        required=True,
        validate=validate.Length(equal=6)
    )
    new_password = fields.Str(
        required=True,
        validate=validate.Length(min=8, max=128)
    )
    
    @validates('code')
    def validate_code(self, value):
        """Validate reset code format"""
        if not value.isdigit():
            raise ValidationError('Reset code must be 6 digits')
    
    @validates('new_password')
    def validate_password(self, value):
        """Validate password strength"""
        if not re.search(r'[A-Z]', value):
            raise ValidationError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', value):
            raise ValidationError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', value):
            raise ValidationError('Password must contain at least one number')
