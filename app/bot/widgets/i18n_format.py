import logging
import re
from re import Match
from typing import Any, Optional, Union

from aiogram_dialog.api.internal import TextWidget
from aiogram_dialog.api.protocols import DialogManager
from aiogram_dialog.widgets.common import WhenCondition
from aiogram_dialog.widgets.text import Text
from magic_filter import MagicFilter

from app.bot.middlewares.i18n import I18nFormatter
from app.core.constants import I18N_FORMATTER_KEY

logger = logging.getLogger(__name__)


def collapse_closing_tags(text: str) -> str:
    def replacer(match: Match) -> str:
        tag = match.group(1)
        content = match.group(2).rstrip()
        return f"<{tag}>{content}</{tag}>"

    return re.sub(
        r"<(\w+)>[\n\r]+(.*?)[\n\r]+</\1>",
        replacer,
        text,
        flags=re.DOTALL,
    )


def default_format_text(text: str, data: dict[str, Any]) -> str:
    return text.format_map(data)


class I18nFormat(Text):
    def __init__(
        self,
        key: str,
        when: Optional[WhenCondition] = None,
        /,
        **mapping: Union[TextWidget, MagicFilter, str, int, float, bool],
    ) -> None:
        super().__init__(when)
        self.key = key
        self.mapping = mapping

    async def _transform(
        self,
        data: dict[str, Any],
        dialog_manager: DialogManager,
    ) -> dict[str, Any]:
        mapped: dict[str, Any] = {}

        for key, transformer in self.mapping.items():
            if isinstance(transformer, TextWidget):
                mapped[key] = await transformer.render_text(data, dialog_manager)
            elif isinstance(transformer, MagicFilter):
                mapped[key] = transformer.resolve(data)
            else:
                mapped[key] = transformer

        logger.debug(f"Key '{self.key}' transformed mapping: {mapped}")
        return {**data, **mapped}

    async def _render_text(self, data: dict[str, Any], dialog_manager: DialogManager) -> str:
        format_value: I18nFormatter = dialog_manager.middleware_data.get(
            I18N_FORMATTER_KEY,
            default_format_text,
        )

        if self.mapping:
            data = await self._transform(data, dialog_manager)

        return collapse_closing_tags(text=format_value(self.key, data))
