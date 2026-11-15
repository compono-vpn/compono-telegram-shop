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


class PendingSetupRemindersKey(StorageKey, prefix="pending_setup_24h"): ...


class SetupFetchWatchKey(StorageKey, prefix="setup_fetch_watch"): ...


class PendingSetupCheckinsKey(StorageKey, prefix="pending_setup_checkin"): ...


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


class SourceSurveyAnsweredKey(StorageKey, prefix="source_survey_answered"):
    """Collapses a double tap on the source survey into one stored answer."""

    telegram_id: int


class PendingPaymentNudgesKey(StorageKey, prefix="pending_payment_nudge"): ...


class PaymentNudgeDataKey(StorageKey, prefix="payment_nudge_data"):
    """What the nudge message needs: payment link, plan name, price (2 days)."""

    payment_id: str


class PaymentNudgeLatestKey(StorageKey, prefix="payment_nudge_latest"):
    """The user's newest payment; older pending ones stay silent."""

    telegram_id: int


class PaymentNudgeSentKey(StorageKey, prefix="payment_nudge_sent"):
    """One nudge per payment, ever (SETNX)."""

    payment_id: str


class PaymentNudgeUserKey(StorageKey, prefix="payment_nudge_user"):
    """At most one nudge per user in a 30 minute window (SETNX)."""

    telegram_id: int
