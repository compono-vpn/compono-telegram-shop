from src.core.storage.key_builder import StorageKey


class WebhookLockKey(StorageKey, prefix="webhook_lock"):
    bot_id: int
    webhook_hash: str


class SyncRunningKey(StorageKey, prefix="sync_running"): ...


class AccessWaitListKey(StorageKey, prefix="access_wait_list"): ...


class RecentActivityUsersKey(StorageKey, prefix="recent_activity_users"): ...


class OtpKey(StorageKey, prefix="otp"):
    email: str


class OtpRateLimitKey(StorageKey, prefix="otp_rate"):
    email: str


class NotificationDedupKey(StorageKey, prefix="ntf_dedup"):
    telegram_id: int
    ntf_type: str


class PendingNotConnectedRemindersKey(StorageKey, prefix="pending_not_connected"): ...
