"""Strict, side-effect-free request contracts for the existing profile routes.

The route module supplies legacy validators so this module only hardens request
shape and sequencing; it does not introduce account-policy changes.
"""
from __future__ import annotations

from datetime import date, datetime
import json
import io
import re
import warnings
import os
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit


MAX_PROFILE_JSON_BYTES = 4096
MAX_PASSWORD_JSON_BYTES = 4096
MAX_PASSWORD_LENGTH = 1024
MAX_AVATAR_BYTES = 5 * 1024 * 1024

PROFILE_FIELDS = frozenset({
    "first_name", "last_name", "phone", "country_code", "date_of_birth", "email",
})
PASSWORD_FIELDS = frozenset({"current_password", "new_password"})
_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp"})


class ProfileContractError(ValueError):
    """A safe request error that can be returned to a client verbatim."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProfileContractError("JSON object contains duplicate fields")
        result[key] = value
    return result


def json_mapping_from_request(request: Any, *, max_bytes: int) -> dict[str, Any]:
    """Read one bounded, JSON-object request without Flask coercion semantics."""
    content_length = request.content_length
    if content_length is not None and content_length > max_bytes:
        raise ProfileContractError("Request body is too large", 413)
    if not request.is_json:
        raise ProfileContractError("JSON request body is required", 415)

    raw = request.stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ProfileContractError("Request body is too large", 413)
    if not raw:
        raise ProfileContractError("JSON request body is required")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except UnicodeDecodeError:
        raise ProfileContractError("JSON request body is invalid") from None
    except json.JSONDecodeError:
        raise ProfileContractError("JSON request body is invalid") from None
    if type(value) is not dict:
        raise ProfileContractError("JSON request body must be an object")
    return value


def _string(value: Any, field: str, *, max_length: int | None = None) -> str:
    if not isinstance(value, str):
        raise ProfileContractError(f"{field} must be a string")
    if max_length is not None and len(value) > max_length:
        raise ProfileContractError(f"{field} is too long")
    return value


def _invalid_from_validator(valid: bool, message: str, fallback: str) -> str:
    return message if not valid and isinstance(message, str) and len(message) <= 160 else fallback


def validate_profile_update(
    payload: Mapping[str, Any],
    *,
    email_validator: Callable[[str], tuple[bool, str]],
    string_validator: Callable[..., tuple[bool, str]],
    phone_validator: Callable[[str], tuple[bool, str | None]],
) -> dict[str, Any]:
    """Validate every permitted profile field before the ORM object is touched."""
    unknown = set(payload).difference(PROFILE_FIELDS)
    if unknown:
        raise ProfileContractError("Profile contains unsupported fields")
    if not payload:
        raise ProfileContractError("At least one profile field is required")

    updates: dict[str, Any] = {}
    if "first_name" in payload:
        value = _string(payload["first_name"], "first_name", max_length=50)
        valid, result = string_validator(value, min_length=2, max_length=50)
        if not valid:
            raise ProfileContractError(_invalid_from_validator(valid, result, "Invalid first name"))
        updates["first_name"] = result

    if "last_name" in payload:
        value = _string(payload["last_name"], "last_name", max_length=50)
        valid, result = string_validator(value, min_length=2, max_length=50)
        if not valid:
            raise ProfileContractError(_invalid_from_validator(valid, result, "Invalid last name"))
        updates["last_name"] = result

    if "phone" in payload:
        value = _string(payload["phone"], "phone", max_length=20)
        valid, result = phone_validator(value)
        if not valid:
            raise ProfileContractError(_invalid_from_validator(valid, result or "", "Invalid phone number"))
        # The legacy phone validator deliberately maps an empty optional phone to None.
        updates["phone"] = result

    if "country_code" in payload:
        value = _string(payload["country_code"], "country_code", max_length=2)
        valid, result = string_validator(value, exact_length=2)
        if not valid:
            raise ProfileContractError("Country code must be 2 characters (ISO 3166-1 alpha-2)")
        updates["country_code"] = result.upper()

    if "date_of_birth" in payload:
        value = _string(payload["date_of_birth"], "date_of_birth", max_length=10)
        try:
            dob = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise ProfileContractError("Invalid date format. Use YYYY-MM-DD") from None
        today = date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age < 18:
            raise ProfileContractError("You must be at least 18 years old")
        if age > 120:
            raise ProfileContractError("Invalid date of birth")
        updates["date_of_birth"] = dob

    if "email" in payload:
        value = _string(payload["email"], "email", max_length=255)
        valid, result = email_validator(value)
        if not valid or not isinstance(result, str) or len(result) > 255:
            raise ProfileContractError("Invalid email address")
        updates["email"] = result

    return updates


def validate_password_change(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Validate both exact password fields and bounds before any hash operation."""
    unknown = set(payload).difference(PASSWORD_FIELDS)
    if unknown:
        raise ProfileContractError("Password request contains unsupported fields")
    missing = PASSWORD_FIELDS.difference(payload)
    if missing:
        raise ProfileContractError("Missing required fields: " + ", ".join(sorted(missing)))

    current_password = _string(payload["current_password"], "current_password", max_length=MAX_PASSWORD_LENGTH)
    new_password = _string(payload["new_password"], "new_password", max_length=MAX_PASSWORD_LENGTH)
    if not current_password or not new_password:
        raise ProfileContractError("Missing required fields: " + ", ".join(
            name for name, value in (("current_password", current_password), ("new_password", new_password)) if not value
        ))

    return current_password, new_password


def validate_new_password_strength(
    password: str, *, password_validator: Callable[[str], tuple[bool, str]]
) -> None:
    """Apply the established strength policy after current-password verification."""
    valid, message = password_validator(password)
    if not valid:
        raise ProfileContractError(_invalid_from_validator(valid, message, "Password does not meet requirements"))


def validate_avatar_file(file: Any) -> str:
    """Bound and inspect actual image bytes, then restore the upload stream."""
    filename = getattr(file, "filename", None)
    if not isinstance(filename, str) or not filename:
        raise ProfileContractError("No file selected")
    if "." not in filename:
        raise ProfileContractError("Invalid file type. Allowed: png, jpg, jpeg, gif, webp")
    extension = filename.rsplit(".", 1)[1].lower()
    if extension not in _IMAGE_EXTENSIONS:
        raise ProfileContractError("Invalid file type. Allowed: png, jpg, jpeg, gif, webp")

    stream = getattr(file, "stream", file)
    try:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        if size <= 0:
            raise ProfileContractError("Invalid image file")
        if size > MAX_AVATAR_BYTES:
            raise ProfileContractError("File size must be less than 5MB")
        stream.seek(0)
        contents = stream.read(MAX_AVATAR_BYTES + 1)
        if len(contents) != size or len(contents) > MAX_AVATAR_BYTES:
            raise ProfileContractError("File size must be less than 5MB")
    except ProfileContractError:
        raise
    except Exception:
        raise ProfileContractError("Unable to read image file") from None
    finally:
        try:
            stream.seek(0)
        except Exception:
            pass

    # A real decoder, not MIME/signature sniffing. Verify checks the container;
    # load checks first-frame compressed pixels. Bound pixels before decoding.
    from PIL import Image
    aliases = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "gif": "GIF", "webp": "WEBP"}
    mime_types = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp"}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(contents)) as image:
                detected = image.format
                if detected != aliases[extension] or image.width * image.height > 20_000_000:
                    raise ProfileContractError("Invalid image file")
                image.verify()
            with Image.open(io.BytesIO(contents)) as image:
                image.load()
    except ProfileContractError:
        raise
    except Exception:
        raise ProfileContractError("Invalid image file") from None
    return mime_types[detected]


def avatar_storage_key(avatar_url: Any, user_id: Any) -> str | None:
    """Return only a canonical key written by the existing profile storage paths."""
    if not isinstance(avatar_url, str) or not isinstance(user_id, int) or isinstance(user_id, bool) or user_id < 1:
        return None
    parsed = urlsplit(avatar_url)
    path = parsed.path
    if not path:
        return None

    # Match the complete storage path, not a prefix that permits traversal.
    pattern = rf"profiles/(?:{user_id}/avatar|profile_{user_id})\.(png|jpg|jpeg|gif|webp)"
    key = None
    if path.startswith("/uploads/") and not parsed.netloc and not parsed.scheme:
        key = path[len("/uploads/"):]
    elif (parsed.scheme == "https" and not parsed.username and not parsed.password
          and re.fullmatch(r"[a-z0-9][a-z0-9-]*\.[a-z0-9-]+\.(?:cdn\.)?digitaloceanspaces\.com", parsed.netloc)):
        key = path.lstrip("/")
    if parsed.query or parsed.fragment or key is None:
        return None
    return key if re.fullmatch(pattern, key) else None


def validate_avatar_storage_result(result: Any, user_id: int, extension: str, cdn_endpoint: str) -> tuple[str, str]:
    """Admit only the adapter's exact local/CDN URL and literal owner key."""
    key = f"profiles/{user_id}/avatar.{extension.lower()}"
    local_url = f"/uploads/{key}"
    if not isinstance(result, dict) or result.get("success") is not True or result.get("key") != key:
        raise ProfileContractError("Avatar upload failed", 503)
    url = result.get("url")
    # Canonical remote endpoint comes from configured StorageService, not a client or URL suffix.
    remote_url = cdn_endpoint.rstrip("/") + "/" + key
    if not isinstance(url, str) or len(url) > 500 or url not in {local_url, remote_url}:
        raise ProfileContractError("Avatar upload failed", 503)
    return url, key
