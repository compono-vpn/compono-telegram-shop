import re
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, field_validator
from pydantic_core.core_schema import FieldValidationInfo

from src.core.constants import API_V1, ASSETS_DIR, DOMAIN_REGEX, PAYMENTS_WEBHOOK_PATH
from src.core.enums import Locale, PaymentGatewayType
from src.core.utils.types import LocaleList, StringList

from .base import BaseConfig
from .bot import BotConfig
from .build import BuildConfig
from .redis import RedisConfig
from .remnawave import RemnawaveConfig
from .validators import validate_not_change_me


class AppConfig(BaseConfig, env_prefix="APP_"):
    domain: SecretStr
    host: str = "0.0.0.0"
    port: int = 5000
    relay_sync_url: str = ""

    locales: LocaleList = LocaleList([Locale.EN])
    default_locale: Locale = Locale.EN

    crypt_key: SecretStr
    assets_dir: Path = ASSETS_DIR
    origins: StringList = StringList("")
    hydra_domains: StringList = StringList("")

    bot: BotConfig = Field(default_factory=BotConfig)
    remnawave: RemnawaveConfig = Field(default_factory=RemnawaveConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    build: BuildConfig = Field(default_factory=BuildConfig)

    resend_api_key: str = ""
    resend_from_email: str = "Compono VPS <noreply@mail.componovps.com>"

    jwt_secret: SecretStr = SecretStr("")
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    jwt_expiry_days: int = 30

    api_url: str = ""
    api_internal_secret: SecretStr = SecretStr("")

    kafka_brokers: str = "kafka-kafka-bootstrap.kafka.svc.cluster.local:9092"
    kafka_topic_env: str = "stage"
    kafka_group_id: str = "compono-shop"

    # Admin feature flag: when False, admin-only Telegram flows (broadcasts,
    # promocode management, settings/config, gateway admin, user-editor) are
    # blocked.  End-user flows (purchase, subscription, referral, support,
    # promocode *activation*) are unaffected.  Default False to enforce
    # "shop is not the admin surface".
    shop_admin_enabled: bool = False

    # URL for the Django web backoffice.  When set and admin features are
    # disabled, blocked admin flows will direct privileged users here.
    admin_portal_url: str = ""

    @property
    def kafka_notify_topic(self) -> str:
        return f"{self.kafka_topic_env}.compono.notify.user.v1"

    # External service base URLs (overridable, non-secret)
    resend_api_base: str = "https://api.resend.com"
    yookassa_api_base: str = "https://api.yookassa.ru"
    yoomoney_api_base: str = "https://yoomoney.ru"
    cryptomus_api_base: str = "https://api.cryptomus.com"
    heleket_api_base: str = "https://api.heleket.com"
    platega_api_base: str = "https://app.platega.io"

    # App URLs (overridable for staging/mirrors)
    trial_return_url: str = "https://componovps.com/trial/success"
    trial_failed_url: str = "https://componovps.com/trial/failed"
    yookassa_receipt_url: str = "https://yookassa.ru/my/i/Z8AkHJ_F9sO_/l"
    portal_url: str = "https://componovpn.org/portal"
    ios_download_url: str = "https://apps.apple.com/app/streisand/id6450534064"
    android_download_url: str = "https://play.google.com/store/apps/details?id=com.v2ray.ang"
    desktop_download_url: str = "https://github.com/hiddify/hiddify-app/releases"

    @property
    def hydra_primary_domain(self) -> str:
        """First domain in HYDRA_DOMAINS list, used as default for fallback URLs."""
        return (
            self.hydra_domains[0]
            if self.hydra_domains and self.hydra_domains[0]
            else "componovpn.com"
        )

    @property
    def hydra_allowed_origins(self) -> set[str]:
        """Set of https:// origins for all hydra domains."""
        return {f"https://{d}" for d in self.hydra_domains if d}

    @property
    def banners_dir(self) -> Path:
        return self.assets_dir / "banners"

    @property
    def translations_dir(self) -> Path:
        return self.assets_dir / "translations"

    def get_webhook(self, gateway_type: PaymentGatewayType) -> str:
        domain = f"https://{self.domain.get_secret_value()}"
        path = f"{API_V1 + PAYMENTS_WEBHOOK_PATH}/{gateway_type.lower()}"
        return domain + path

    @classmethod
    def get(cls) -> Self:
        return cls()

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, field: SecretStr, info: FieldValidationInfo) -> SecretStr:
        validate_not_change_me(field, info)

        if not re.match(DOMAIN_REGEX, field.get_secret_value()):
            raise ValueError("APP_DOMAIN has invalid format")

        return field

    @field_validator("crypt_key")
    @classmethod
    def validate_crypt_key(cls, field: SecretStr, info: FieldValidationInfo) -> SecretStr:
        validate_not_change_me(field, info)

        if not re.match(r"^[A-Za-z0-9+/=]{44}$", field.get_secret_value()):
            raise ValueError("APP_CRYPT_KEY must be a valid 44-character Base64 string")

        return field
