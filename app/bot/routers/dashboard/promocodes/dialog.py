from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.kbd import Button, Row, Start

from app.bot.states import Dashboard, DashboardPromocodes
from app.bot.widgets import Banner, I18nFormat, IgnoreUpdate
from app.core.enums import BannerName

promocodes = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocodes-main"),
    Row(
        Button(
            text=I18nFormat("btn-promocodes-list"),
            id="list",
        ),
        Button(
            text=I18nFormat("btn-promocodes-search"),
            id="search",
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-promocodes-create"),
            id="create",
        ),
        # Button(
        #     text=I18nFormat("btn-promocodes-delete"),
        #     id="delete",
        # ),
        # Button(
        #     text=I18nFormat("btn-promocodes-edit"),
        #     id="edit",
        # ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back"),
            id="back",
            state=Dashboard.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.MAIN,
)

router = Dialog(
    promocodes,
)
