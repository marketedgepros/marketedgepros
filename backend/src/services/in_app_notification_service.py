"""Durable in-app notification helpers.

This module intentionally has no dependency on the monitoring ``NotificationService``.
It writes only the existing ``notifications`` table and never sends email, SMS,
Slack, or enqueues an ``EmailQueue`` record.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.database import db
from src.models.notification import Notification, NotificationPreference


NOTIFICATION_TYPES = frozenset({
    "withdrawal", "commission", "kyc", "system", "payment", "challenge",
})
NOTIFICATION_PRIORITIES = frozenset({"low", "normal", "high", "urgent"})
PREFERENCE_CATEGORIES = (
    "withdrawal", "commission", "kyc", "system", "payment", "challenge",
)
EMAIL_FREQUENCIES = frozenset({"instant", "daily", "weekly"})


class InAppNotificationService:
    """Small persistence-only API for the existing in-app notification schema."""

    @staticmethod
    def create_notification(
        *,
        user_id: int,
        notification_type: str,
        title: str,
        message: str,
        data: dict[str, Any] | list[Any] | None = None,
        priority: str = "normal",
        commit: bool = True,
    ) -> Notification:
        """Create an in-app record only.

        Callers that already own a wider transaction can pass ``commit=False``.
        This deliberately does not inspect notification preferences: preference
        evaluation and producer integration are outside this containment change.
        """
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
            raise ValueError("Invalid notification user")
        if notification_type not in NOTIFICATION_TYPES:
            raise ValueError("Invalid notification type")
        if priority not in NOTIFICATION_PRIORITIES:
            raise ValueError("Invalid notification priority")
        if not isinstance(title, str) or not title.strip() or len(title) > 255:
            raise ValueError("Invalid notification title")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Invalid notification message")
        if data is not None and not isinstance(data, (dict, list)):
            raise ValueError("Invalid notification data")

        notification = Notification(
            user_id=user_id,
            type=notification_type,
            title=title.strip(),
            message=message.strip(),
            data=data,
            priority=priority,
        )
        try:
            db.session.add(notification)
            if commit:
                db.session.commit()
            return notification
        except Exception:
            if commit:
                db.session.rollback()
            raise

    @staticmethod
    def preference_defaults(*, user_id: int) -> dict[str, Any]:
        """Return the model's explicit default representation without a flush."""
        return {
            "id": None,
            "user_id": user_id,
            "persisted": False,
            "in_app": {category: True for category in PREFERENCE_CATEGORIES},
            "email": {
                category: category != "system" for category in PREFERENCE_CATEGORIES
            },
            "settings": {
                "email_enabled": True,
                "email_frequency": "instant",
            },
        }

    @classmethod
    def serialize_preferences(
        cls, prefs: NotificationPreference | None, *, user_id: int
    ) -> dict[str, Any]:
        if prefs is None:
            return cls.preference_defaults(user_id=user_id)
        return {
            "id": prefs.id,
            "user_id": prefs.user_id,
            "persisted": True,
            "in_app": {
                category: getattr(prefs, f"in_app_{category}")
                for category in PREFERENCE_CATEGORIES
            },
            "email": {
                category: getattr(prefs, f"email_{category}")
                for category in PREFERENCE_CATEGORIES
            },
            "settings": {
                "email_enabled": prefs.email_enabled,
                "email_frequency": prefs.email_frequency,
            },
        }

    @staticmethod
    def get_preferences_read_only(user_id: int) -> NotificationPreference | None:
        """Fetch preferences without autoflushing or creating a default row."""
        with db.session.no_autoflush:
            return db.session.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == user_id
                )
            ).scalar_one_or_none()

    @staticmethod
    def apply_preference_changes(
        prefs: NotificationPreference, changes: dict[str, Any]
    ) -> None:
        for channel in ("in_app", "email"):
            values = changes.get(channel)
            if values:
                for category, value in values.items():
                    setattr(prefs, f"{channel}_{category}", value)
        settings = changes.get("settings")
        if settings:
            for key, value in settings.items():
                setattr(prefs, key, value)

    @classmethod
    def update_preferences(
        cls, *, user_id: int, changes: dict[str, Any]
    ) -> NotificationPreference:
        """Atomically upsert a user's unique preference row.

        The unique ``user_id`` constraint remains the race gate.  An insert is
        first flushed inside a savepoint, allowing a concurrent winner to be
        re-read without using the legacy auto-committing ``get_or_create``.
        There is one outer commit for the mutation and a rollback on failure.
        """
        try:
            prefs = cls.get_preferences_read_only(user_id)
            if prefs is None:
                candidate = NotificationPreference(user_id=user_id)
                try:
                    with db.session.begin_nested():
                        db.session.add(candidate)
                        db.session.flush()
                    prefs = candidate
                except IntegrityError:
                    # A concurrent request inserted the one allowed row.  The
                    # savepoint rollback leaves the outer request usable.
                    prefs = cls.get_preferences_read_only(user_id)
                    if prefs is None:
                        raise
            cls.apply_preference_changes(prefs, changes)
            db.session.commit()
            return prefs
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def mark_read(notification: Notification) -> bool:
        """Mutate an owned notification in the caller's transaction."""
        if notification.is_read:
            return False
        notification.is_read = True
        notification.read_at = datetime.utcnow()
        return True

    @staticmethod
    def soft_delete(notification: Notification) -> None:
        """Soft-delete an owned notification in the caller's transaction."""
        notification.is_deleted = True
        notification.deleted_at = datetime.utcnow()
