import logging
from pathlib import Path
from typing import Optional

from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.common import Whenable
from aiogram_dialog.widgets.media import StaticMedia

from app.bot.models.containers import AppContainer
from app.core.config import DEFAULT_BANNERS_DIR
from app.core.constants import APP_CONTAINER_KEY
from app.core.enums import BannerFormat, BannerName

logger = logging.getLogger(__name__)


class Banner(StaticMedia):
    def __init__(self, name: BannerName) -> None:
        path: Optional[Path] = None
        content_type: Optional[str] = None

        for format in BannerFormat:
            candidate_path = DEFAULT_BANNERS_DIR / f"{name.value}.{format.value}"
            if candidate_path.exists():
                path = candidate_path
                content_type = format.content_type
                logger.debug(f"Using banner file: {path} with content type: {content_type}")
                break

        if path is None:
            logger.warning(f"Banner file for '{name.value}' not found (using default)")
            path = DEFAULT_BANNERS_DIR / f"{BannerName.DEFAULT.value}.{BannerFormat.JPG.value}"
            content_type = BannerFormat.JPG.content_type

        if not path.exists():
            raise FileNotFoundError(f"Default banner file not found: {path}")

        def is_use_banners(data: dict, widget: Whenable, dialog_manager: DialogManager) -> bool:
            container: AppContainer = dialog_manager.middleware_data[APP_CONTAINER_KEY]
            return container.config.bot.use_banners

        super().__init__(path=path, type=content_type, when=is_use_banners)
