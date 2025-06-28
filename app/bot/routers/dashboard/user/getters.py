from aiogram_dialog import DialogManager

from app.bot.models import AppContainer
from app.core.enums import UserRole


async def user_getter(dialog_manager: DialogManager, container: AppContainer, **kwargs) -> dict:
    target_telegram_id = dialog_manager.start_data.get("target_telegram_id")
    target_user = await container.services.user.get(telegram_id=target_telegram_id)

    return {
        "id": str(target_user.telegram_id),
        "name": target_user.name,
        "role": target_user.role,
        "is_blocked": target_user.is_blocked,
        "status": None,
    }


async def role_getter(dialog_manager: DialogManager, container: AppContainer, **kwargs) -> dict:
    target_telegram_id = dialog_manager.start_data.get("target_telegram_id")
    target_user = await container.services.user.get(telegram_id=target_telegram_id)
    roles = [role for role in UserRole if role != target_user.role]

    return {"roles": roles}
