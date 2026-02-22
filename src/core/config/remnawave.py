import re

from httpx import Cookies
from pydantic import SecretStr, field_validator
from pydantic_core.core_schema import FieldValidationInfo

from src.core.constants import DOMAIN_REGEX, URL_PATTERN

from .base import BaseConfig
from .validators import validate_not_change_me


class RemnawaveConfig(BaseConfig, env_prefix="REMNAWAVE_"):
    host: SecretStr = SecretStr("remnawave")
    port: int = 3000
    token: SecretStr
    caddy_token: SecretStr = SecretStr("")
    webhook_secret: SecretStr
    cookie: SecretStr = SecretStr("")

    @property
    def is_raw_url(self) -> bool:
        return bool(re.match(URL_PATTERN, self.host.get_secret_value()))

    @property
    def is_external(self) -> bool:
        host = self.host.get_secret_value()
        return host != "remnawave" and not self.is_raw_url

    @property
    def url(self) -> SecretStr:
        host = self.host.get_secret_value()
        if self.is_raw_url:
            return SecretStr(host.rstrip("/"))
        elif self.is_external:
            return SecretStr(f"https://{host}")
        else:
            return SecretStr(f"http://{host}:{self.port}")

    @property
    def cookies(self) -> Cookies:
        cookie = self.cookie.get_secret_value()
        cookies = Cookies()

        if not self.cookie:
            return cookies

        key, value = cookie.split("=", 1)
        cookies.set(key.strip(), value.strip())

        return cookies

    @field_validator("host")
    @classmethod
    def validate_host(cls, field: SecretStr, info: FieldValidationInfo) -> SecretStr:
        host = field.get_secret_value()

        if host == "remnawave" or re.match(DOMAIN_REGEX, host) or re.match(URL_PATTERN, host):
            validate_not_change_me(field, info)
            return field

        raise ValueError(
            "REMNAWAVE_HOST must be 'remnawave' (docker), a valid domain, or a full URL (e.g., http://service:3000)"
        )

    @field_validator("token")
    @classmethod
    def validate_remnawave_token(cls, field: SecretStr, info: FieldValidationInfo) -> SecretStr:
        validate_not_change_me(field, info)
        return field

    @field_validator("webhook_secret")
    @classmethod
    def validate_remnawave_webhook_secret(
        cls,
        field: SecretStr,
        info: FieldValidationInfo,
    ) -> SecretStr:
        validate_not_change_me(field, info)
        return field

    @field_validator("cookie")
    @classmethod
    def validate_cookie(cls, field: SecretStr) -> SecretStr:
        cookie = field.get_secret_value()

        if not cookie:
            return field

        cookie = cookie.strip()

        if "=" not in cookie or cookie.startswith("=") or cookie.endswith("="):
            raise ValueError("REMNAWAVE_COOKIE must be in 'key=value' format")

        return field
