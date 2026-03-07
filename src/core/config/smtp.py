from pydantic import SecretStr

from .base import BaseConfig


class SmtpConfig(BaseConfig, env_prefix="SMTP_"):
    host: str = ""
    port: int = 587
    username: str = ""
    password: SecretStr = SecretStr("")
    from_email: str = ""
    from_name: str = "Compono VPS"
