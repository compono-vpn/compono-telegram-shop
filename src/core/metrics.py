from prometheus_client import Counter, Gauge, Histogram

UPDATE_PROCESSING_TIME = Histogram(
    "bot_update_processing_seconds",
    "Time spent processing a Telegram update end-to-end",
    ["update_type"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

MIDDLEWARE_PROCESSING_TIME = Histogram(
    "bot_middleware_processing_seconds",
    "Time spent in each middleware",
    ["middleware"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

UPDATES_TOTAL = Counter(
    "bot_updates_total",
    "Total number of Telegram updates received",
    ["update_type"],
)

ERRORS_TOTAL = Counter(
    "bot_errors_total",
    "Total number of unexpected errors",
    ["error_type", "source"],
)

THROTTLED_REQUESTS_TOTAL = Counter(
    "bot_throttled_requests_total",
    "Total number of throttled user requests",
)

NEW_USERS_TOTAL = Counter(
    "bot_new_users_total",
    "Total number of new user registrations",
)

PAYMENT_WEBHOOK_PROCESSING_TIME = Histogram(
    "payment_webhook_processing_seconds",
    "Time spent processing payment webhooks",
    ["gateway_type"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

PAYMENT_WEBHOOK_ERRORS_TOTAL = Counter(
    "payment_webhook_errors_total",
    "Total number of payment webhook errors",
    ["gateway_type"],
)

TASKIQ_TASK_DURATION = Histogram(
    "taskiq_task_duration_seconds",
    "Time spent executing taskiq tasks",
    ["task_name"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

TASKIQ_TASK_ERRORS_TOTAL = Counter(
    "taskiq_task_errors_total",
    "Total number of taskiq task errors",
    ["task_name", "error_type"],
)

BOT_INFO = Gauge(
    "bot_info",
    "Bot version information",
    ["version"],
)
