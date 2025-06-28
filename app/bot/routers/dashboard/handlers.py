import logging

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Select

from app.bot.models.containers import AppContainer
from app.core.constants import APP_CONTAINER_KEY, USER_KEY
from app.core.enums import MaintenanceMode
from app.core.formatters import format_log_user
from app.db.models.dto import UserDto

logger = logging.getLogger(__name__)


async def on_maintenance_mode_selected(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_mode: str,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    container: AppContainer = dialog_manager.middleware_data[APP_CONTAINER_KEY]

    await container.services.maintenance.set_mode(MaintenanceMode(selected_mode))
    logger.info(f"{format_log_user(user)} Set maintenance mode -> '{selected_mode}'")
