from loguru import logger
from prometheus_client import Counter, Gauge, Histogram, start_http_server

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

EXPERIMENT_EXPOSURES_TOTAL = Counter(
    "bot_experiment_exposures_total",
    "Distinct users first exposed to an experiment variant",
    ["experiment", "variant"],
)

EXPERIMENT_CONVERSIONS_TOTAL = Counter(
    "bot_experiment_conversions_total",
    "Experiment conversion events by variant",
    ["experiment", "variant", "event"],
)

KAFKA_CONSUMER_UP = Gauge(
    "kafka_consumer_up",
    "Whether a Kafka consumer's consume loop is currently running (1) or down/restarting (0)",
    ["consumer"],
)

KAFKA_CONSUMER_RESTARTS_TOTAL = Counter(
    "kafka_consumer_restarts_total",
    "Total number of times a Kafka consumer's consume loop crashed and was restarted",
    ["consumer"],
)


CANCEL_SURVEY_SENT_TOTAL = Counter(
    "bot_cancel_survey_sent_total",
    "Cancel-reason survey prompts sent, by payment gateway",
    ["gateway"],
)

CANCEL_SURVEY_ANSWERS_TOTAL = Counter(
    "bot_cancel_survey_answers_total",
    "Cancel-reason survey answers, by reason and payment gateway",
    ["reason", "gateway"],
)


def start_metrics_server(port: int) -> None:
    """Expose the process-local Prometheus registry over HTTP.

    The taskiq worker process (where the Kafka consumers run) has no other
    HTTP surface, so consumer liveness metrics would otherwise be registered
    but never scrapeable. Safe to call unconditionally: failures (e.g. the
    port already bound) are logged, never raised, so they can't block worker
    startup.
    """
    try:
        start_http_server(port)
        logger.info(f"Metrics HTTP server listening on port {port}")
    except OSError:
        logger.warning(f"Could not start metrics HTTP server on port {port}")
