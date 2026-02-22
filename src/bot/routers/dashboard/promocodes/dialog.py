from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Column, Row, ScrollingGroup, Select, Start, SwitchTo
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.bot.keyboards import main_menu_button
from src.bot.states import Dashboard, DashboardPromocodes
from src.bot.widgets import Banner, I18nFormat, IgnoreUpdate
from src.core.enums import BannerName, PromocodeAvailability, PromocodeRewardType

from .getters import configurator_getter, list_getter
from .handlers import (
    on_active_toggle,
    on_availability_select,
    on_code_input,
    on_confirm,
    on_delete,
    on_lifetime_input,
    on_list,
    on_list_select,
    on_reward_input,
    on_search_input,
    on_type_select,
)

promocodes = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocodes-main"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-promocodes-create"),
            id="create",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-promocodes-list"),
            id="list",
            on_click=on_list,
        ),
        SwitchTo(
            text=I18nFormat("btn-promocodes-search"),
            id="search",
            state=DashboardPromocodes.ALLOWED,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back"),
            id="back",
            state=Dashboard.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        *main_menu_button,
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.MAIN,
)

configurator = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-configurator"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-promocode-code"),
            id="code",
            state=DashboardPromocodes.CODE,
        ),
        SwitchTo(
            text=I18nFormat("btn-promocode-type"),
            id="type",
            state=DashboardPromocodes.TYPE,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-promocode-availability"),
            id="availability",
            state=DashboardPromocodes.AVAILABILITY,
        ),
        Button(
            text=I18nFormat("btn-promocode-active", is_active=F["is_active"]),
            id="active_toggle",
            on_click=on_active_toggle,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-promocode-reward"),
            id="reward",
            state=DashboardPromocodes.REWARD,
        ),
        SwitchTo(
            text=I18nFormat("btn-promocode-lifetime"),
            id="lifetime",
            state=DashboardPromocodes.LIFETIME,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-promocode-allowed"),
            id="allowed",
            state=DashboardPromocodes.ALLOWED,
            when=F["availability"] == PromocodeAvailability.ALLOWED,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-promocode-confirm"),
            id="confirm",
            on_click=on_confirm,
        ),
        Button(
            text=I18nFormat("btn-promocodes-delete"),
            id="delete",
            on_click=on_delete,
            when=F["id"],
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardPromocodes.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.CONFIGURATOR,
    getter=configurator_getter,
)

code_input = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-code-input"),
    MessageInput(func=on_code_input),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.CODE,
)

type_select = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-type-select"),
    Column(
        Select(
            text=Format("{item}"),
            id="type_select",
            item_id_getter=lambda item: item,
            items=[t.value for t in PromocodeRewardType],
            type_factory=PromocodeRewardType,
            on_click=on_type_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.TYPE,
)

availability_select = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-availability-select"),
    Column(
        Select(
            text=Format("{item}"),
            id="availability_select",
            item_id_getter=lambda item: item,
            items=[a.value for a in PromocodeAvailability],
            type_factory=PromocodeAvailability,
            on_click=on_availability_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.AVAILABILITY,
)

reward_input = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-reward-input"),
    MessageInput(func=on_reward_input),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.REWARD,
)

lifetime_input = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-lifetime-input"),
    MessageInput(func=on_lifetime_input),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.LIFETIME,
)

promocode_list = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocodes-list"),
    ScrollingGroup(
        Select(
            text=Format("{item[name]}"),
            id="promocode_select",
            item_id_getter=lambda item: item["id"],
            items="promocodes",
            type_factory=int,
            on_click=on_list_select,
        ),
        id="promocodes_scroll",
        width=1,
        height=8,
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardPromocodes.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.LIST,
    getter=list_getter,
)

search_input = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-search-input"),
    MessageInput(func=on_search_input),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardPromocodes.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.ALLOWED,
)

router = Dialog(
    promocodes,
    configurator,
    code_input,
    type_select,
    availability_select,
    reward_input,
    lifetime_input,
    promocode_list,
    search_input,
)
