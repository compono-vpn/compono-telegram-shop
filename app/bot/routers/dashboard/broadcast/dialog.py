from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.kbd import Button, Row, Start

from app.bot.states import Dashboard, DashboardBroadcast
from app.bot.widgets import Banner, I18nFormat, IgnoreUpdate
from app.core.enums import BannerName

broadcast = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-broadcast-main"),
    Row(
        Button(
            I18nFormat("btn-broadcast-all"),
            id="all",
        ),
        Button(
            I18nFormat("btn-broadcast-user"),
            id="user",
        ),
    ),
    Row(
        Button(
            I18nFormat("btn-broadcast-subscribed"),
            id="subscribed",
        ),
        Button(
            I18nFormat("btn-broadcast-unsubscribed"),
            id="unsubscribed",
        ),
    ),
    Row(
        Button(
            I18nFormat("btn-broadcast-expired"),
            id="expired",
        ),
    ),
    Row(
        Button(
            I18nFormat("btn-broadcast-last-message"),
            id="last_message",
        ),
    ),
    Row(
        Start(
            I18nFormat("btn-back"),
            id="back",
            state=Dashboard.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardBroadcast.MAIN,
)


router = Dialog(broadcast)
