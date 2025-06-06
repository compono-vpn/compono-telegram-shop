from datetime import timezone

DOMAIN_REGEX = r"^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$"
API_V1: str = "/api/v1"
WEBHOOK_PATH: str = "/webhook"
HEADER_SECRET_TOKEN: str = "x-telegram-bot-api-secret-token"
TIMEZONE = timezone.utc
UNLIMITED = "∞"

# Resource file names for i18n
RESOURCE_I18N = ["messages.ftl", "buttons.ftl", "notifications.ftl", "popups.ftl"]

# NOTE: think about a class for typed storage
# Keys for data
MIDDLEWARE_DATA_KEY = "middleware_data"
AUDIT_KEY = "audit"
USER_KEY = "user"
USER_SERVICE_KEY = "user_service"
THROTTLING_KEY = "throttling_key"
I18N_MIDDLEWARE_KEY = "i18n_middleware"
SESSION_POOL_KEY = "session_pool"
I18N_FORMAT_KEY = "i18n_format"
CONFIG_KEY = "config"
REMNAWAVE_KEY = "remnawave"
BOT_KEY = "bot"
