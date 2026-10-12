"""Profile management routes."""
import logging
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from src.database import db
from src.models.user import EmailVerificationToken, PasswordResetToken, User
from src.services.profile_contract import (
    MAX_PASSWORD_JSON_BYTES,
    MAX_PROFILE_JSON_BYTES,
    ProfileContractError,
    avatar_storage_key,
    json_mapping_from_request,
    validate_avatar_file,
    validate_avatar_storage_result,
    validate_password_change,
    validate_new_password_strength,
    validate_profile_update,
)
from src.services.storage_service import storage_service
from src.utils.decorators import token_required
from src.utils.validators import (
    validate_email_format,
    validate_password_strength,
    validate_phone_number,
    validate_string,
)

logger = logging.getLogger(__name__)
profile_bp = Blueprint("profile", __name__)


def _contract_error(error: ProfileContractError):
    return jsonify({"error": error.message}), error.status


def _rollback_contract_error(error: ProfileContractError):
    """Release a principal lock while retaining the safe validation response."""
    db.session.rollback()
    return _contract_error(error)


@profile_bp.route("", methods=["GET"])
@token_required
def get_profile(current_user):
    """Get the existing full authenticated-user profile representation."""
    try:
        # include_sensitive has never included credentials/secrets; it preserves
        # the existing auth response shape (verification/KYC timestamps included).
        return jsonify({"user": g.current_user.to_dict(include_sensitive=True)}), 200
    except Exception:
        return jsonify({"error": "Failed to get profile"}), 500


@profile_bp.route("", methods=["PUT"])
@token_required
def update_profile(current_user):
    """Atomically update allowed profile fields after whole-request validation."""
    try:
        payload = json_mapping_from_request(request, max_bytes=MAX_PROFILE_JSON_BYTES)
        updates = validate_profile_update(
            payload,
            email_validator=validate_email_format,
            string_validator=validate_string,
            phone_validator=validate_phone_number,
        )
    except ProfileContractError as error:
        return _contract_error(error)

    try:
        from src.services.session_service import SessionService

        # Do not mutate the authentication decorator's potentially stale object.
        # The locked principal serializes profile/email/session-sensitive changes.
        user = SessionService.principal(SessionService.payload(g.token), lock=True)

        new_email = updates.get("email")
        if new_email is not None and new_email != user.email:
            existing_user = User.query.filter_by(email=new_email).first()
            if existing_user is not None:
                return _rollback_contract_error(ProfileContractError("Email already in use"))

        # Every request field has now been parsed and validated. No early
        # assignment can leave a dirty ORM object on a later validation failure.
        for field, value in updates.items():
            if field != "email":
                setattr(user, field, value)

        if new_email is not None and new_email != user.email:
            user.email = new_email
            user.is_verified = False
            user.email_verified_at = None
            user.token_version = (user.token_version or 0) + 1
            for model in (EmailVerificationToken, PasswordResetToken):
                db.session.query(model).filter(
                    model.user_id == user.id, model.used.is_(False)
                ).update({"used": True}, synchronize_session=False)

        db.session.commit()
        return jsonify({
            "message": "Profile updated successfully",
            "user": user.to_dict(include_sensitive=True),
        }), 200
    except ValueError:
        db.session.rollback()
        return jsonify({"error": "Invalid or revoked session"}), 401
    except Exception:
        db.session.rollback()
        logger.exception("Profile update failed")
        return jsonify({"error": "Failed to update profile"}), 500


@profile_bp.route("/password", methods=["PUT"])
@token_required
def change_password(current_user):
    """Change password and revoke all issued credentials in one database commit."""
    try:
        payload = json_mapping_from_request(request, max_bytes=MAX_PASSWORD_JSON_BYTES)
        current_password, new_password = validate_password_change(payload)
    except ProfileContractError as error:
        return _contract_error(error)

    try:
        from src.services.session_service import SessionService

        user = SessionService.principal(SessionService.payload(g.token), lock=True)
        if not user.check_password(current_password):
            return _rollback_contract_error(ProfileContractError("Current password is incorrect", 401))
        try:
            validate_new_password_strength(
                new_password, password_validator=validate_password_strength
            )
        except ProfileContractError as error:
            return _rollback_contract_error(error)
        if user.check_password(new_password):
            return _rollback_contract_error(ProfileContractError(
                "New password must be different from current password"
            ))

        user.set_password(new_password)
        user.token_version = (user.token_version or 0) + 1
        db.session.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id, PasswordResetToken.used.is_(False)
        ).update({"used": True}, synchronize_session=False)
        db.session.commit()
        # Earlier access/refresh tokens fail the established token-version check.
        return jsonify({"message": "Password changed successfully"}), 200
    except ValueError:
        db.session.rollback()
        return jsonify({"error": "Invalid or revoked session"}), 401
    except Exception:
        db.session.rollback()
        logger.exception("Password change failed")
        return jsonify({"error": "Failed to change password"}), 500


@profile_bp.route("/avatar", methods=["POST"])
@token_required
def upload_avatar(current_user):
    """Validate actual image bytes, then persist avatar metadata only after upload."""
    if "avatar" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["avatar"]
    try:
        image_mime = validate_avatar_file(file)
        # StorageService reads Content-Type from the upload; never trust client MIME.
        file.headers["Content-Type"] = image_mime
    except ProfileContractError as error:
        return _contract_error(error)

    uploaded_key = None
    try:
        from src.services.session_service import SessionService

        user = SessionService.principal(SessionService.payload(g.token), lock=True)
        result = storage_service.upload_profile_image(file, user.id)
        try:
            url, uploaded_key = validate_avatar_storage_result(
                result, user.id, file.filename.rsplit(".", 1)[1], storage_service.cdn_endpoint
            )
        except ProfileContractError as error:
            return _rollback_contract_error(error)

        user.avatar_url = url
        db.session.commit()
        return jsonify({
            "message": "Avatar uploaded successfully",
            "avatar_url": url,
            "user": user.to_dict(),
        }), 200
    except ValueError:
        db.session.rollback()
        return jsonify({"error": "Invalid or revoked session"}), 401
    except Exception:
        db.session.rollback()
        # A failed DB commit must not be reported as an avatar success. When the
        # adapter supplied a canonical key, make a best-effort orphan cleanup;
        # cleanup failure is deliberately not exposed to the caller.
        if uploaded_key is not None:
            try:
                storage_service.delete_file(uploaded_key)
            except Exception:
                pass
        logger.exception("Avatar upload failed")
        return jsonify({"error": "Avatar upload failed"}), 500


@profile_bp.route("/avatar", methods=["DELETE"])
@token_required
def delete_avatar(current_user):
    """Delete avatar metadata only after the known storage object is deleted."""
    try:
        from src.services.session_service import SessionService

        user = SessionService.principal(SessionService.payload(g.token), lock=True)
        if not user.avatar_url:
            db.session.rollback()
            return jsonify({"message": "No avatar to delete", "user": user.to_dict()}), 200

        key = avatar_storage_key(user.avatar_url, user.id)
        if key is None:
            db.session.rollback()
            return jsonify({"error": "Avatar deletion failed"}), 503

        try:
            deleted = storage_service.delete_file(key)
        except Exception:
            deleted = False
        if deleted is not True:
            # Keep the persisted metadata when the remote/local deletion is not
            # confirmed; it is more truthful than returning a false success.
            db.session.rollback()
            return jsonify({"error": "Avatar deletion failed"}), 503

        user.avatar_url = None
        db.session.commit()
        return jsonify({
            "message": "Avatar deleted successfully",
            "user": user.to_dict(),
        }), 200
    except ValueError:
        db.session.rollback()
        return jsonify({"error": "Invalid or revoked session"}), 401
    except Exception:
        db.session.rollback()
        logger.exception("Avatar deletion failed")
        return jsonify({"error": "Avatar deletion failed"}), 500


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
