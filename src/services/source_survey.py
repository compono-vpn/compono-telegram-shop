import re
import unicodedata
from datetime import timedelta
from typing import Optional

from loguru import logger

from src.bot.keyboards import get_source_survey_keyboard
from src.core.metrics import SOURCE_SURVEY_SENT_TOTAL
from src.core.utils.message_payload import MessagePayload
from src.core.utils.time import datetime_now
from src.infrastructure.billing import BillingClient
from src.models.dto import UserDto
from src.services.notification import NotificationService

KIND = "SOURCE_SURVEY"
DEDUP_KEY = "v1"
MAX_ACCOUNT_AGE = timedelta(days=7)
MAX_TEXT_LENGTH = 200

_WHITESPACE = re.compile(r"\s+")


def is_eligible(user: UserDto) -> bool:
    if user.source and user.source.strip():
        return False
    if user.created_at is not None and datetime_now() - user.created_at > MAX_ACCOUNT_AGE:
        return False
    return True


def sanitize_free_text(raw: Optional[str]) -> str:
    if not raw:
        return ""
    kept = [
        " " if char.isspace() else char
        for char in raw
        if char.isspace() or unicodedata.category(char) not in {"Cc", "Cf", "Cs", "Co", "Cn"}
    ]
    text = _WHITESPACE.sub(" ", "".join(kept)).strip()
    return text[:MAX_TEXT_LENGTH].strip()


async def offer_source_survey(
    *,
    user: UserDto,
    billing: BillingClient,
    notification_service: NotificationService,
) -> bool:
    if not is_eligible(user):
        return False

    try:
        if not await billing.claim_user_reminder(user.telegram_id, KIND, DEDUP_KEY):
            return False
    except Exception:
        logger.opt(exception=True).warning(
            f"Could not claim the source survey for '{user.telegram_id}'"
        )
        return False

    try:
        message = await notification_service.notify_user(
            user=user,
            payload=MessagePayload(
                i18n_key="ntf-source-survey-prompt",
                reply_markup=get_source_survey_keyboard(),
                auto_delete_after=None,
                add_close_button=False,
            ),
        )
    except Exception:
        logger.opt(exception=True).warning(
            f"Could not send the source survey to '{user.telegram_id}'"
        )
        try:
            await billing.release_user_reminder(user.telegram_id, KIND, DEDUP_KEY)
        except Exception:
            logger.opt(exception=True).warning(
                f"Could not release the source survey claim for '{user.telegram_id}'"
            )
        return False

    if message is None:
        return False

    SOURCE_SURVEY_SENT_TOTAL.inc()
    logger.info(f"Sent the source survey to '{user.telegram_id}'")
    return True
