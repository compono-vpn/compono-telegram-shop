from aiogram_dialog import DialogManager

from app.bot.models import AppContainer
from app.core.formatters import format_percent


async def blacklist_getter(
    dialog_manager: DialogManager,
    container: AppContainer,
    **kwargs,
) -> dict:
    blocked_users = await container.services.user.get_blocked_users()
    users = await container.services.user.count()

    return {
        "blocked_users_exists": bool(blocked_users),
        "blocked_users": blocked_users,
        "count_blocked": len(blocked_users),
        "count_users": users,
        "percent": format_percent(part=len(blocked_users), whole=users),
    }
