from typing import Any

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from src.core.constants import USER_KEY


class PrivilegedFilter(BaseFilter):
    """Lets only an ADMIN or DEV into the admin dialogs.

    Callback data is not trusted: aiogram-dialog handles a hidden button and any widget id the
    callback carries, so the role is checked here, not only by `when` on the buttons.
    """

    async def __call__(self, event: TelegramObject, **data: Any) -> bool:
        user = data.get(USER_KEY)
        return bool(user is not None and user.is_privileged)
