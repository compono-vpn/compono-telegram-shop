from src.core.utils.key_builder import StorageKey


class WebhookLockKey(StorageKey, prefix="webhook_lock"):
    bot_id: int
    webhook_hash: str


class MaintenanceModeKey(StorageKey, prefix="maintenance_mode"):
    pass


class MaintenanceWaitListKey(StorageKey, prefix="maintenance_wait_list"):
    pass


class DefaultCurrencyKey(StorageKey, prefix="default_currency"):
    pass


class SystemNotificationSettingsKey(StorageKey, prefix="system_notification_settings"):
    pass


class UserNotificationSettingsKey(StorageKey, prefix="user_notification_settings"):
    pass


class RecentRegisteredUsersKey(StorageKey, prefix="recent_registered_users"):
    pass


class RecentActivityUsersKey(StorageKey, prefix="recent_activity_users"):
    pass
