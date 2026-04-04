"""Shared admin dialog handlers.

Extracted from broadcast.handlers during admin surface reduction so that
the user-management dialog can continue using on_content_input / on_preview
without depending on the removed broadcast module.
"""

from __future__ import annotations

import html
from typing import Any, Optional

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.core.constants import USER_KEY
from src.core.enums import MediaType
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.models.dto import UserDto
from src.services.notification import NotificationService


def _update_payload(dialog_manager: DialogManager, **updates: Any) -> MessagePayload:
    raw_payload = dialog_manager.dialog_data.get("payload")

    old_payload = (
        MessagePayload.model_validate(raw_payload)
        if raw_payload
        else MessagePayload(
            i18n_key="ntf-broadcast-preview",
            auto_delete_after=None,
            add_close_button=True,
        )
    )

    payload_data = old_payload.model_dump()
    payload_data.update(updates)

    new_payload = MessagePayload(**payload_data)
    dialog_manager.dialog_data["payload"] = new_payload.model_dump()

    return new_payload


@inject
async def on_content_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    logger.debug(f"{log(user)} Attempted to set content")

    media_type: Optional[MediaType] = None
    file_id: Optional[str] = None

    if message.photo:
        media_type = MediaType.PHOTO
        file_id = message.photo[-1].file_id
    elif message.video:
        media_type = MediaType.VIDEO
        file_id = message.video.file_id
    elif message.document:
        media_type = MediaType.DOCUMENT
        file_id = message.document.file_id
    elif message.sticker:
        media_type = MediaType.DOCUMENT
        file_id = message.sticker.file_id

    if not (message.html_text or file_id):
        logger.warning(f"{log(user)} Provided invalid or empty content")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-broadcast-wrong-content"),
        )
        return

    _update_payload(
        dialog_manager,
        i18n_kwargs={"content": html.unescape(message.html_text)},
        media_type=media_type,
        media_id=file_id,
    )

    logger.info(f"{log(user)} Updated message payload (content only)")
    await notification_service.notify_user(
        user=user,
        payload=MessagePayload(i18n_key="ntf-broadcast-content-saved"),
    )


@inject
async def on_preview(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    payload = dialog_manager.dialog_data.get("payload")

    if not payload:
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-broadcast-empty-content"),
        )
        return

    await notification_service.notify_user(
        user=user, payload=MessagePayload.model_validate(payload)
    )
