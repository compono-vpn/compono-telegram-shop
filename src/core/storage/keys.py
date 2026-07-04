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
