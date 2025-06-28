from datetime import timezone

DOMAIN_REGEX = r"^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$"
API_V1: str = "/api/v1"
WEBHOOK_PATH: str = "/webhook"
HEADER_SECRET_TOKEN: str = "x-telegram-bot-api-secret-token"
TIMEZONE = timezone.utc
UNLIMITED = "∞"

# Resource file names for i18n
RESOURCE_I18N = ["messages.ftl", "buttons.ftl", "notifications.ftl", "popups.ftl", "utils.ftl"]

# Keys for data
DIALOG_MANAGER_KEY = "dialog_manager"
MIDDLEWARE_DATA_KEY = "middleware_data"
APP_CONTAINER_KEY = "container"
BOT_KEY = "bot"
USER_KEY = "user"
THROTTLING_KEY = "throttling_key"
I18N_FORMATTER_KEY = "i18n_formatter"
MAINTENANCE_KEY = "maintenance_mode"
MAINTENANCE_WAITLIST_KEY = "maintenance_waiting_users"
