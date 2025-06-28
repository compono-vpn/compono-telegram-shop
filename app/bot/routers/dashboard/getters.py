from aiogram_dialog import DialogManager

from app.bot.models.containers import AppContainer


async def maintenance_getter(
    dialog_manager: DialogManager,
    container: AppContainer,
    **kwargs,
) -> dict:
    current_mode = await container.services.maintenance.get_mode()
    modes = await container.services.maintenance.get_available_modes()

    return {
        "status": current_mode,
        "modes": modes,
    }
