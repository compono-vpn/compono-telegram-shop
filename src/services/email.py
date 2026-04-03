import httpx
from loguru import logger

from src.core.config import AppConfig


class EmailService:
    def __init__(self, config: AppConfig) -> None:
        self.api_key = config.resend_api_key
        self.from_email = config.resend_from_email
        self.resend_api_base = config.resend_api_base
        self.ios_download_url = config.ios_download_url
        self.android_download_url = config.android_download_url
        self.desktop_download_url = config.desktop_download_url

    async def send_otp_code(self, to_email: str, code: str) -> None:
        if not self.api_key:
            logger.warning(f"Resend API key not configured, skipping OTP email to '{to_email}'")
            return

        html = f"""\
<div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 24px;">
    <h2 style="margin-bottom: 16px;">Вход в Compono</h2>
    <p>Ваш код подтверждения:</p>
    <div style="margin: 24px 0; padding: 16px; background: #f5f5f5; border: 1px solid #ddd;
                border-radius: 8px; text-align: center;">
        <span style="font-size: 32px; font-weight: bold;
              letter-spacing: 8px; font-family: monospace;">
            {code}
        </span>
    </div>
    <p style="color: #666; font-size: 14px;">Код действителен 5 минут.
        Если вы не запрашивали код, проигнорируйте это письмо.</p>
    <hr style="margin-top: 32px; border: none; border-top: 1px solid #eee;">
    <p style="color: #999; font-size: 12px;">Compono VPN — быстрый и безопасный интернет</p>
</div>"""

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.resend_api_base}/emails",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "from": self.from_email,
                        "to": [to_email],
                        "subject": "Compono — код подтверждения",
                        "html": html,
                    },
                )
                resp.raise_for_status()
                logger.info(f"OTP email sent to '{to_email}', id={resp.json().get('id')}")
        except Exception as e:
            logger.error(f"Failed to send OTP email to '{to_email}': {e}")

    async def send_trial_bot_link(self, to_email: str, bot_link: str) -> None:
        if not self.api_key:
            logger.warning(f"Resend API key not configured, skipping email to '{to_email}'")
            return

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

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.resend_api_base}/emails",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "from": self.from_email,
                        "to": [to_email],
                        "subject": "Compono VPS — ваш доступ готов",
                        "html": html,
                    },
                )
                resp.raise_for_status()
                logger.info(f"Trial email sent to '{to_email}', id={resp.json().get('id')}")
        except Exception as e:
            logger.error(f"Failed to send email to '{to_email}': {e}")

    async def send_purchase_subscription(
        self,
        to_email: str,
        subscription_url: str,
        plan_name: str,
        bot_link: str = "",
    ) -> None:
        if not self.api_key:
            logger.warning(f"Resend API key not configured, skipping email to '{to_email}'")
            return

        bot_section = ""
        if bot_link:
            bot_section = f"""\
    <h3 style="margin-top: 24px;">Привязать к Telegram</h3>
    <p>Привяжите подписку к Telegram-боту, чтобы управлять ей,
        получать уведомления и продлевать:</p>
    <p style="margin: 16px 0;">
        <a href="{bot_link}"
           style="display: inline-block; padding: 12px 24px; background: #FFD600;
                  color: #1A1A1A; text-decoration: none; font-weight: bold;
                  border: 3px solid #1A1A1A;">
            Открыть в Telegram
        </a>
    </p>"""

        html = f"""\
<div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 24px;">
    <h2 style="margin-bottom: 16px;">Добро пожаловать в Compono VPN!</h2>
    <p>Ваша подписка <strong>{plan_name}</strong> активирована.</p>
    <p>Скопируйте ссылку ниже и добавьте её
        в ваш VPN-клиент:</p>
    <div style="margin: 16px 0; padding: 12px; background: #f5f5f5; border: 1px solid #ddd;
                border-radius: 4px; word-break: break-all;
                font-family: monospace; font-size: 13px;">
        {subscription_url}
    </div>
    <h3 style="margin-top: 24px;">Как подключиться</h3>
    <ol style="padding-left: 20px; line-height: 1.8;">
        <li>Скачайте VPN-клиент для вашего устройства</li>
        <li>Скопируйте ссылку подписки выше</li>
        <li>Добавьте её в клиент как подписку</li>
    </ol>
    <p style="margin-top: 16px;"><strong>Скачать клиент:</strong></p>
    <ul style="list-style: none; padding: 0;">
        <li style="margin: 8px 0;">
            <a href="{self.ios_download_url}">iOS — Streisand</a>
        </li>
        <li style="margin: 8px 0;">
            <a href="{self.android_download_url}">Android — v2rayNG</a>
        </li>
        <li style="margin: 8px 0;">
            <a href="{self.desktop_download_url}">Windows / macOS — Hiddify</a>
        </li>
    </ul>
    {bot_section}
    <hr style="margin-top: 32px; border: none; border-top: 1px solid #eee;">
    <p style="color: #999; font-size: 12px;">Compono VPN — быстрый и безопасный интернет</p>
</div>"""

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.resend_api_base}/emails",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "from": self.from_email,
                        "to": [to_email],
                        "subject": f"Compono VPN — ваша подписка {plan_name} активирована",
                        "html": html,
                    },
                )
                resp.raise_for_status()
                logger.info(f"Purchase email sent to '{to_email}', id={resp.json().get('id')}")
        except Exception as e:
            logger.error(f"Failed to send purchase email to '{to_email}': {e}")
