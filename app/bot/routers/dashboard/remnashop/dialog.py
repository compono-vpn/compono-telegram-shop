from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.kbd import Button, ListGroup, Row, Start, SwitchTo
from aiogram_dialog.widgets.text import Format

from app.bot.routers.dashboard.users.handlers import on_user_selected
from app.bot.states import Dashboard, DashboardRemnashop, RemnashopPlans
from app.bot.widgets import Banner, I18nFormat, IgnoreUpdate
from app.core.enums import BannerName

from .getters import admins_getter
from .handlers import on_user_role_removed

remnashop = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnashop-main"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-remnashop-admins"),
            id="admins",
            state=DashboardRemnashop.ADMINS,
        )
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-remnashop-referral"),
            id="referral",
            state=DashboardRemnashop.REFERRAL,
        ),
        SwitchTo(
            text=I18nFormat("btn-remnashop-advertising"),
            id="advertising",
            state=DashboardRemnashop.ADVERTISING,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-remnashop-plans"),
            id="plans",
            state=RemnashopPlans.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        SwitchTo(
            text=I18nFormat("btn-remnashop-notifications"),
            id="notifications",
            state=DashboardRemnashop.NOTIFICATIONS,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-remnashop-logs"),
            id="logs",
        ),
        Button(
            text=I18nFormat("btn-remnashop-audit"),
            id="audit",
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back"),
            id="back",
            state=Dashboard.MAIN,
            mode=StartMode.RESET_STACK,
        )
    ),
    IgnoreUpdate(),
    state=DashboardRemnashop.MAIN,
)


admins = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnashop-admins"),
    ListGroup(
        Row(
            Button(
                text=Format("{item.telegram_id} ({item.name})"),
                id="select_user",
                on_click=on_user_selected,
            ),
            Button(
                text=Format("❌"),
                id="remove_role",
                on_click=on_user_role_removed,
            ),
        ),
        id="admins_list",
        item_id_getter=lambda item: item.telegram_id,
        items="admins",
    ),
    Row(
        Start(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardRemnashop.MAIN,
            mode=StartMode.RESET_STACK,
        )
    ),
    IgnoreUpdate(),
    state=DashboardRemnashop.ADMINS,
    getter=admins_getter,
)

router = Dialog(
    remnashop,
    admins,
)
