from uuid import UUID

from src.core.storage.key_builder import StorageKey


class WebhookLockKey(StorageKey, prefix="webhook_lock"):
    bot_id: int


class PurchaseIdempotencyKey(StorageKey, prefix="purchase_idem"):
    """Guards purchase/renew/change taskiq tasks against re-mutating
    Remnawave (or re-applying renew/change expiry) when a task for the
    same payment is retried or re-delivered after a mid-task crash."""

    payment_id: UUID


class TrialIdempotencyKey(StorageKey, prefix="trial_idem"):
    """Guards trial_subscription_task against provisioning a second
    Remnawave user when retried/re-delivered for the same telegram user."""

    telegram_id: int


class SyncRunningKey(StorageKey, prefix="sync_running"): ...


class AccessWaitListKey(StorageKey, prefix="access_wait_list"): ...


class RecentActivityUsersKey(StorageKey, prefix="recent_activity_users"): ...


class NotificationDedupKey(StorageKey, prefix="ntf_dedup"):
    telegram_id: int
    ntf_type: str


class PendingNotConnectedRemindersKey(StorageKey, prefix="pending_not_connected"): ...


class PendingCancelSurveyChecksKey(StorageKey, prefix="pending_cancel_survey"): ...


class CancelSurveySentKey(StorageKey, prefix="cancel_survey_sent"):
    """Guards the cancel-reason survey sweep against sending a second
    prompt for the same transaction (SETNX, 90d TTL)."""

    payment_id: UUID


class CancelSurveyAnswerKey(StorageKey, prefix="cancel_survey"):
    """Redis hash storing the recorded answer for a cancel-reason survey."""

    payment_id: UUID


class CancelSurveyAwaitingTextKey(StorageKey, prefix="cancel_survey_awaiting_text"):
    """Marks a user as mid-reply to the survey's free-text ('Другое') prompt."""

    telegram_id: int


class CancelSurveyPendingPingKey(StorageKey, prefix="cancel_survey_pending_ping"):
    """Guards the pending checkout reminder so it is sent only once."""

    payment_id: UUID
