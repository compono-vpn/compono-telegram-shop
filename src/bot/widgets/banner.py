import functools
from pathlib import Path
from typing import Any, Optional

from aiogram.types import ContentType
from aiogram_dialog import DialogManager
from aiogram_dialog.api.entities import MediaAttachment
from aiogram_dialog.widgets.common import Whenable
from aiogram_dialog.widgets.media import StaticMedia
from loguru import logger

from src.core.config import AppConfig
from src.core.constants import CONFIG_KEY, USER_KEY
from src.core.enums import BannerFormat, BannerName, Locale
from src.models.dto import UserDto


@functools.lru_cache(maxsize=None)
def get_banner(
    banners_dir: Path,
    name: BannerName,
    locale: Locale,
    default_locale: Locale,
) -> tuple[Path, ContentType]:
    def find_in_dirs(dirs: list[Path], filenames: list[str]) -> tuple[Path, ContentType] | None:
        for directory in dirs:
            if not directory.exists():
                continue
            for pattern in filenames:
                for format in BannerFormat:
                    filename = pattern.format(format=format)
                    candidate = directory / filename
                    if candidate.exists():
                        return candidate, format.content_type
        return None

    locale_dirs = [banners_dir / locale, banners_dir / default_locale]

    result = find_in_dirs(
        locale_dirs, filenames=[f"{name}.{{format}}", f"{BannerName.DEFAULT}.{{format}}"]
    )
    if result:
        return result

    result = find_in_dirs([banners_dir], [f"{name}.{{format}}", f"{BannerName.DEFAULT}.{{format}}"])
    if result:
        logger.debug(
            f"Banner '{name}' not found in locales"
            f" '{locale}' or '{default_locale}', using global fallback"
        )
        return result

    raise FileNotFoundError(
        f"Banner '{name}' not found in locales '{locale}', '{default_locale}', or globally"
    )


class Banner(StaticMedia):
    def __init__(self, name: BannerName) -> None:
        self.banner_name = name

        def _is_use_banners(
            data: dict[str, Any],
            widget: Whenable,
            dialog_manager: DialogManager,
        ) -> bool:
            config: AppConfig = dialog_manager.middleware_data[CONFIG_KEY]
            return config.bot.use_banners

        super().__init__(path="path", url=None, type=ContentType.UNKNOWN, when=_is_use_banners)

    async def _render_media(self, data: dict, manager: DialogManager) -> Optional[MediaAttachment]:
        user: UserDto = manager.middleware_data[USER_KEY]
        config: AppConfig = manager.middleware_data[CONFIG_KEY]

        banner_path, banner_content_type = get_banner(
            banners_dir=config.banners_dir,
            name=self.banner_name,
            locale=user.language,
            default_locale=config.default_locale,
        )

        return MediaAttachment(
            type=banner_content_type,
            url=None,
            path=banner_path,
            use_pipe=self.use_pipe,
            **self.media_params,
        )
