import re
from re import Match
from typing import Any, Protocol

from aiogram_dialog.api.protocols import DialogManager
from aiogram_dialog.widgets.common import WhenCondition
from aiogram_dialog.widgets.text import Text

from app.bot.middlewares.i18n import I18nFormatter
from app.core.constants import I18N_FORMAT_KEY


class Values(Protocol):
    def __getitem__(self, item: Any) -> Any:
        raise NotImplementedError


def flatten_dict(data: dict[str, Any], parent_key: str = "", sep: str = "_") -> dict[str, Any]:
    items = {}
    for key, value in data.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, dict):
            items.update(flatten_dict(value, new_key, sep=sep))
        else:
            items[new_key] = value
    return items


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


def default_format_text(text: str, data: Values) -> str:
    return text.format_map(data)


class I18nFormat(Text):
    def __init__(self, key: str, when: WhenCondition = None) -> None:
        super().__init__(when)
        self.key = key

    async def _render_text(self, data: dict, manager: DialogManager) -> str:
        i18n_format: I18nFormatter = manager.middleware_data.get(
            I18N_FORMAT_KEY,
            default_format_text,
        )
        return collapse_closing_tags(i18n_format(self.key, flatten_dict(data)))
