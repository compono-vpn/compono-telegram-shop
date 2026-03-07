import aiosmtplib
from email.message import EmailMessage

from loguru import logger

from src.core.config import AppConfig


class EmailService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config.smtp

    async def send_trial_bot_link(self, to_email: str, bot_link: str) -> None:
        if not self.config.host:
            logger.warning(f"SMTP not configured, skipping email to '{to_email}'")
            return

        subject = "Compono VPS — ваш доступ готов"
        html = f"""\
<div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 24px;">
    <h2 style="margin-bottom: 16px;">Добро пожаловать в Compono VPS!</h2>
    <p>Ваш пробный период на 3 дня активирован.</p>
    <p>Нажмите кнопку ниже, чтобы получить данные для подключения в Telegram:</p>
    <p style="margin: 24px 0;">
        <a href="{bot_link}"
           style="display: inline-block; padding: 14px 28px; background: #FFD600;
                  color: #1A1A1A; text-decoration: none; font-weight: bold;
                  border: 3px solid #1A1A1A;">
            Открыть в Telegram
        </a>
    </p>
    <p style="color: #666; font-size: 14px;">
        Если кнопка не работает, скопируйте ссылку:<br>
        <a href="{bot_link}">{bot_link}</a>
    </p>
    <hr style="margin-top: 32px; border: none; border-top: 1px solid #eee;">
    <p style="color: #999; font-size: 12px;">Compono VPS — быстрый и безопасный интернет</p>
</div>"""

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"{self.config.from_name} <{self.config.from_email}>"
        msg["To"] = to_email
        msg.set_content(f"Compono VPS — ваш доступ готов. Откройте ссылку: {bot_link}")
        msg.add_alternative(html, subtype="html")

        try:
            await aiosmtplib.send(
                msg,
                hostname=self.config.host,
                port=self.config.port,
                username=self.config.username,
                password=self.config.password.get_secret_value(),
                use_tls=self.config.port == 465,
                start_tls=self.config.port == 587,
            )
            logger.info(f"Trial email sent to '{to_email}'")
        except Exception as e:
            logger.error(f"Failed to send email to '{to_email}': {e}")
