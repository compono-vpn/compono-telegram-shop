import httpx
from loguru import logger

from src.core.config import AppConfig


class EmailService:
    def __init__(self, config: AppConfig) -> None:
        self.api_key = config.resend_api_key
        self.from_email = config.resend_from_email

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
                    "https://api.resend.com/emails",
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
        self, to_email: str, subscription_url: str, plan_name: str
    ) -> None:
        if not self.api_key:
            logger.warning(f"Resend API key not configured, skipping email to '{to_email}'")
            return

        html = f"""\
<div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 24px;">
    <h2 style="margin-bottom: 16px;">Добро пожаловать в Compono VPN!</h2>
    <p>Ваша подписка <strong>{plan_name}</strong> активирована.</p>
    <p>Скопируйте ссылку ниже и добавьте её в ваш VPN-клиент:</p>
    <div style="margin: 16px 0; padding: 12px; background: #f5f5f5; border: 1px solid #ddd;
                border-radius: 4px; word-break: break-all; font-family: monospace; font-size: 13px;">
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
            <a href="https://apps.apple.com/app/streisand/id6450534064">iOS — Streisand</a>
        </li>
        <li style="margin: 8px 0;">
            <a href="https://play.google.com/store/apps/details?id=com.v2ray.ang">Android — v2rayNG</a>
        </li>
        <li style="margin: 8px 0;">
            <a href="https://github.com/hiddify/hiddify-app/releases">Windows / macOS — Hiddify</a>
        </li>
    </ul>
    <hr style="margin-top: 32px; border: none; border-top: 1px solid #eee;">
    <p style="color: #999; font-size: 12px;">Compono VPN — быстрый и безопасный интернет</p>
</div>"""

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "from": self.from_email,
                        "to": [to_email],
                        "subject": f"Compono VPN — ваша подписка {plan_name} активирована",
                        "html": html,
                    },
                )
                resp.raise_for_status()
                logger.info(
                    f"Purchase email sent to '{to_email}', id={resp.json().get('id')}"
                )
        except Exception as e:
            logger.error(f"Failed to send purchase email to '{to_email}': {e}")
