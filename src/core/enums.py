from enum import Enum, StrEnum, auto
from typing import Any, Callable

from aiogram import Bot
from aiogram.types import BotCommand, ContentType


class MessageEffect(StrEnum):
    FIRE = "5104841245755180586"  #     🔥
    LIKE = "5107584321108051014"  #     👍
    DISLIKE = "5104858069142078462"  #  👎
    LOVE = "5044134455711629726"  #     ❤️
    CONFETTI = "5046509860389126442"  # 🎉
    POOP = "5046589136895476101"  #     💩


class BannerName(StrEnum):
    DEFAULT = auto()
    MENU = auto()
    DASHBOARD = auto()


class BannerFormat(StrEnum):
    JPG = auto()
    JPEG = auto()
    PNG = auto()
    GIF = auto()
    WEBP = auto()

    @property
    def content_type(self) -> ContentType:
        return {
            BannerFormat.JPG: ContentType.PHOTO,
            BannerFormat.JPEG: ContentType.PHOTO,
            BannerFormat.PNG: ContentType.PHOTO,
            BannerFormat.GIF: ContentType.ANIMATION,
            BannerFormat.WEBP: ContentType.PHOTO,
        }[self]


class MediaType(StrEnum):
    PHOTO = auto()
    VIDEO = auto()
    DOCUMENT = auto()

    def get_function(self, bot_instance: Bot) -> Callable[..., Any]:
        match self:
            case MediaType.PHOTO:
                return bot_instance.send_photo
            case MediaType.VIDEO:
                return bot_instance.send_video
            case MediaType.DOCUMENT:
                return bot_instance.send_document


class SystemNotificationType(StrEnum):
    BOT_LIFETIME = auto()
    USER_REGISTERED = auto()
    SUBSCRIPTION = auto()
    PROMOCODE_ACTIVATED = auto()


class UserNotificationType(StrEnum):
    pass


class UserRole(StrEnum):
    DEV = auto()
    ADMIN = auto()
    USER = auto()


class PromocodeType(StrEnum):
    DURATION = auto()
    TRAFFIC = auto()
    SUBSCRIPTION = auto()
    PERSONAL_DISCOUNT = auto()
    PURCHASE_DISCOUNT = auto()


class PlanType(StrEnum):
    TRAFFIC = auto()
    DEVICES = auto()
    BOTH = auto()
    UNLIMITED = auto()


class PlanAvailability(StrEnum):
    ALL = auto()
    NEW = auto()
    EXISTING = auto()
    INVITED = auto()
    ALLOWED = auto()


class Currency(str, Enum):
    USD = "USD"
    XTR = "XTR"
    RUB = "RUB"

    @property
    def symbol(self) -> str:
        symbols = {
            "USD": "$",
            "XTR": "★",
            "RUB": "₽",
        }
        return symbols[self.value]

    @classmethod
    def from_code(cls, code: str) -> "Currency":
        code = code.upper()
        return cls(code)


class PaymentGatewayType(StrEnum):
    TELEGRAM_STARS = auto()
    YOOKASSA = auto()
    YOOMONEY = auto()
    CRYPTOMUS = auto()
    HELEKET = auto()
    # TRIBUTE = auto()


class MaintenanceMode(StrEnum):
    GLOBAL = auto()
    PURCHASE = auto()
    OFF = auto()


class Command(Enum):
    START = BotCommand(command="start", description="cmd-start")
    # HELP = BotCommand(command="help", description="cmd-help")


class Locale(StrEnum):
    AR = auto()  # Arabic
    AZ = auto()  # Azerbaijani
    BE = auto()  # Belarusian
    CS = auto()  # Czech
    DE = auto()  # German
    EN = auto()  # English
    ES = auto()  # Spanish
    FA = auto()  # Persian
    FR = auto()  # French
    HE = auto()  # Hebrew
    HI = auto()  # Hindi
    ID = auto()  # Indonesian
    IT = auto()  # Italian
    JA = auto()  # Japanese
    KK = auto()  # Kazakh
    KO = auto()  # Korean
    MS = auto()  # Malay
    NL = auto()  # Dutch
    PL = auto()  # Polish
    PT = auto()  # Portuguese
    RO = auto()  # Romanian
    RU = auto()  # Russian
    SR = auto()  # Serbian
    TR = auto()  # Turkish
    UK = auto()  # Ukrainian
    UZ = auto()  # Uzbek
    VI = auto()  # Vietnamese


class MiddlewareEventType(StrEnum):  # https://docs.aiogram.dev/en/latest/api/types/update.html
    AIOGD_UPDATE = auto()  # AIOGRAM DIALOGS
    UPDATE = auto()
    MESSAGE = auto()
    EDITED_MESSAGE = auto()
    CHANNEL_POST = auto()
    EDITED_CHANNEL_POST = auto()
    BUSINESS_CONNECTION = auto()
    BUSINESS_MESSAGE = auto()
    EDITED_BUSINESS_MESSAGE = auto()
    DELETED_BUSINESS_MESSAGES = auto()
    MESSAGE_REACTION = auto()
    MESSAGE_REACTION_COUNT = auto()
    INLINE_QUERY = auto()
    CHOSEN_INLINE_RESULT = auto()
    CALLBACK_QUERY = auto()
    SHIPPING_QUERY = auto()
    PRE_CHECKOUT_QUERY = auto()
    PURCHASED_PAID_MEDIA = auto()
    POLL = auto()
    POLL_ANSWER = auto()
    MY_CHAT_MEMBER = auto()
    CHAT_MEMBER = auto()
    CHAT_JOIN_REQUEST = auto()
    CHAT_BOOST = auto()
    REMOVED_CHAT_BOOST = auto()
    ERROR = auto()
