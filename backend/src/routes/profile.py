"""
Profile management routes
"""
from flask import Blueprint, request, jsonify, g
from src.database import db
from src.utils.decorators import token_required
from src.utils.validators import (
    validate_email_format,
    validate_password_strength,
    validate_required_fields,
    validate_string,
    validate_phone_number
)
from src.services.storage_service import storage_service
from datetime import datetime

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("", methods=["GET"])
@token_required
def get_profile(current_user):
    """Get current user profile"""
    try:
        return jsonify({
            "user": g.current_user.to_dict(include_sensitive=True)
        }), 200
    except Exception as e:
        return jsonify({"error": "Failed to get profile"}), 500


@profile_bp.route("", methods=["PUT"])
@token_required
def update_profile(current_user):
    """Update user profile"""
    data = request.get_json()
    
    try:
        from src.services.session_service import SessionService
        user = SessionService.principal(SessionService.payload(g.token), lock=True)
        
        # Update allowed fields
        if "first_name" in data:
            valid, message = validate_string(data["first_name"], min_length=2, max_length=50)
            if not valid:
                return jsonify({"error": message}), 400
            user.first_name = data["first_name"].strip()
        
        if "last_name" in data:
            valid, message = validate_string(data["last_name"], min_length=2, max_length=50)
            if not valid:
                return jsonify({"error": message}), 400
            user.last_name = data["last_name"].strip()
        
        if "phone" in data:
            valid, phone = validate_phone_number(data["phone"])
            if not valid:
                return jsonify({"error": phone}), 400
            user.phone = phone
        
        if "country_code" in data:
            valid, message = validate_string(data["country_code"], exact_length=2)
            if not valid:
                return jsonify({"error": "Country code must be 2 characters (ISO 3166-1 alpha-2)"}), 400
            user.country_code = data["country_code"].upper()
        
        if "date_of_birth" in data:
            if data["date_of_birth"]:
                try:
                    # Parse date in format YYYY-MM-DD
                    dob = datetime.strptime(data["date_of_birth"], "%Y-%m-%d").date()
                    
                    # Validate age (must be at least 18 years old)
                    today = datetime.now().date()
                    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                    
                    if age < 18:
                        return jsonify({"error": "You must be at least 18 years old"}), 400
                    
                    if age > 120:
                        return jsonify({"error": "Invalid date of birth"}), 400
                    
                    user.date_of_birth = dob
                except ValueError:
                    return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
        
        # Email change requires verification
        if "email" in data and data["email"] != user.email:
            # Validate email format
            valid, result = validate_email_format(data["email"])
            if not valid:
                return jsonify({"error": f"Invalid email: {result}"}), 400
            
            # Check if email already exists
            from src.models.user import User
            existing_user = User.query.filter_by(email=result).first()
            if existing_user:
                return jsonify({"error": "Email already in use"}), 400
            
            # Update email and mark as unverified
            user.email = result
            user.is_verified = False
            user.email_verified_at = None
            user.token_version = (user.token_version or 0) + 1
            from src.models.user import EmailVerificationToken, PasswordResetToken
            for model in (EmailVerificationToken, PasswordResetToken):
                db.session.query(model).filter(model.user_id == user.id, model.used.is_(False)).update(
                    {'used': True}, synchronize_session=False)
            
            # TODO (Phase 4 - Email Notifications): Send verification email to new address
        
        db.session.commit()
        
        return jsonify({
            "message": "Profile updated successfully",
            "user": user.to_dict(include_sensitive=True)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to update profile"}), 500


@profile_bp.route("/password", methods=["PUT"])
@token_required
def change_password(current_user):
    """Change user password"""
    data = request.get_json()
    
    # Validate required fields
    valid, message = validate_required_fields(data, ["current_password", "new_password"])
    if not valid:
        return jsonify({"error": message}), 400
    
    try:
        from src.services.session_service import SessionService
        user = SessionService.principal(SessionService.payload(g.token), lock=True)
        
        # Verify current password
        if not user.check_password(data["current_password"]):
            return jsonify({"error": "Current password is incorrect"}), 401
        
        # Validate new password strength
        valid, message = validate_password_strength(data["new_password"])
        if not valid:
            return jsonify({"error": message}), 400
        
        # Check if new password is same as current
        if user.check_password(data["new_password"]):
            return jsonify({"error": "New password must be different from current password"}), 400
        
        # Update password
        user.set_password(data["new_password"])
        user.token_version = (user.token_version or 0) + 1
        from src.models.user import PasswordResetToken
        db.session.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id, PasswordResetToken.used.is_(False)
        ).update({'used': True}, synchronize_session=False)
        db.session.commit()
        
        # TODO (Phase 4 - Email Notifications): Send password change notification email
        # Access and refresh tokens with earlier versions now fail validation.
        
        return jsonify({
            "message": "Password changed successfully"
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to change password"}), 500


@profile_bp.route("/avatar", methods=["POST"])
@token_required
def upload_avatar(current_user):
    """Upload user avatar"""
    try:
        if "avatar" not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files["avatar"]
        
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400
        
        # Validate file type
        allowed_extensions = {"png", "jpg", "jpeg", "gif", "webp"}
        file_ext = file.filename.rsplit(".", 1)[1].lower() if "." in file.filename else ""
        
        if file_ext not in allowed_extensions:
            return jsonify({"error": f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"}), 400
        
        # Validate file size (max 5MB)
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to beginning
        
        max_size = 5 * 1024 * 1024  # 5MB
        if file_size > max_size:
            return jsonify({"error": "File size must be less than 5MB"}), 400
        
        # Upload file to DigitalOcean Spaces
        user = g.current_user
        
        # Use storage_service to upload profile image
        result = storage_service.upload_profile_image(file, user.id)
        
        if not result.get("success"):
            return jsonify({"error": result.get("error", "Failed to upload avatar")}), 500
        
        url = result["url"]
        
        # Update user avatar URL in database
        user.avatar_url = url
        db.session.commit()
        
        return jsonify({
            "message": "Avatar uploaded successfully",
            "avatar_url": url,
            "user": user.to_dict()
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Failed to upload avatar: {str(e)}"}), 500


@profile_bp.route("/avatar", methods=["DELETE"])
@token_required
def delete_avatar(current_user):
    """Delete user avatar"""
    try:
        user = g.current_user
        
        # Delete avatar file from storage
        if user.avatar_url:
            try:
                # Extract key from URL if it"s a full URL
                if "digitaloceanspaces.com" in user.avatar_url:
                    # Extract key from URL
                    key = user.avatar_url.split(".com/")[-1].split("?")[0]
                    storage_service.delete_file(key)
            except:
                pass  # Ignore if file doesn"t exist
        
        # Update user avatar_url to None in database
        user.avatar_url = None
        db.session.commit()
        
        return jsonify({
            "message": "Avatar deleted successfully",
            "user": user.to_dict()
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Failed to delete avatar: {str(e)}"}), 500


@profile_bp.route("/stats", methods=["GET"])
@token_required
def get_profile_stats(current_user):
    """Get user profile statistics"""
    try:
        user = g.current_user
        
        # Get user statistics
        stats = {
            "total_challenges": 0,
            "active_challenges": 0,
            "passed_challenges": 0,
            "failed_challenges": 0,
            "total_profit": 0.0,
            "total_loss": 0.0,
            "win_rate": 0.0,
            "account_age_days": 0
        }
        
        # Calculate account age
        if user.created_at:
            account_age = datetime.utcnow() - user.created_at
            stats["account_age_days"] = account_age.days
        
        # TODO (Phase 6 - Analytics): Calculate challenge statistics from database
        # This requires querying the Challenge model
        
        return jsonify({
            "stats": stats
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Failed to get stats: {str(e)}"}), 500
