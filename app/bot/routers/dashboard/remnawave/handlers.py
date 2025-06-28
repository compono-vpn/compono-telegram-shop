import logging

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, StartMode
from aiogram_dialog.widgets.kbd import Button

from app.bot.models.containers import AppContainer
from app.bot.states import DashboardRemnawave
from app.core.constants import APP_CONTAINER_KEY

logger = logging.getLogger(__name__)


async def start_remnawave_window(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
):
    container: AppContainer = dialog_manager.middleware_data[APP_CONTAINER_KEY]

    try:
        response = await container.remnawave.system.get_stats()
    except Exception as exception:
        logger.error(f"Remnawave: {exception}")
        # TODO: service notification
        await callback.message.answer(f"Failed to connect to Remnawave. {response}")
        return

    await dialog_manager.start(DashboardRemnawave.MAIN, mode=StartMode.RESET_STACK)
