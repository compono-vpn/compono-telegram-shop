from typing import Optional

from aiogram.fsm.state import State, StatesGroup


class MainMenu(StatesGroup):
    MAIN = State()
    DEVICES = State()
    INVITE = State()
    INVITE_ABOUT = State()
    INFO = State()
    TG_PROXY = State()


class Notification(StatesGroup):
    CLOSE = State()


class Subscription(StatesGroup):
    MAIN = State()
    PROMOCODE = State()
    PROMOCODE_SUCCESS = State()
    PLANS = State()
    DURATION = State()
    PAYMENT_METHOD = State()
    CONFIRM = State()
    SUCCESS = State()
    FAILED = State()
    TRIAL = State()


class Dashboard(StatesGroup):
    MAIN = State()


class DashboardStatistics(StatesGroup):
    MAIN = State()


class DashboardUsers(StatesGroup):
    MAIN = State()
    SEARCH = State()
    SEARCH_RESULTS = State()
    RECENT_REGISTERED = State()
    RECENT_ACTIVITY = State()
    BLACKLIST = State()


class DashboardUser(StatesGroup):
    MAIN = State()
    SUBSCRIPTION = State()
    TRAFFIC_LIMIT = State()
    DEVICE_LIMIT = State()
    EXPIRE_TIME = State()
    SQUADS = State()
    INTERNAL_SQUADS = State()
    EXTERNAL_SQUADS = State()
    DEVICES_LIST = State()
    DISCOUNT = State()
    POINTS = State()
    STATISTICS = State()
    ROLE = State()
    TRANSACTIONS_LIST = State()
    TRANSACTION = State()
    GIVE_ACCESS = State()
    MESSAGE = State()
    SYNC = State()
    SYNC_WAITING = State()
    GIVE_SUBSCRIPTION = State()
    SUBSCRIPTION_DURATION = State()


def state_from_string(state_str: str, sep: Optional[str] = ":") -> Optional[State]:
    try:
        group_name, state_name = state_str.split(":")[:2]
        group_cls = globals().get(group_name)
        if group_cls is None:
            return None
        state_obj = getattr(group_cls, state_name, None)
        if not isinstance(state_obj, State):
            return None
        return state_obj
    except (ValueError, AttributeError):
        return None
