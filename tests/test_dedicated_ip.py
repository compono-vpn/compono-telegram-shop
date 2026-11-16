from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import Message
from aiogram_dialog import BgManagerFactory
from fluentogram import TranslatorHub
from fluentogram.storage import FileStorage
from pydantic import SecretStr
from remnapy.enums.users import TrafficLimitStrategy

from src.bot.keyboards import get_dedicated_ip_keyboard
from src.bot.routers.extra import dedicated_ip as dedicated_ip_router
from src.bot.routers.extra.dedicated_ip import on_dedicated_ip_country, provision_command
from src.bot.routers.subscription.dialog import subscription as subscription_window
from src.bot.routers.subscription.getters import plans_getter as _plans_getter
from src.bot.routers.subscription.getters import subscription_getter as _subscription_getter
from src.bot.routers.subscription.handlers import on_dedicated_ip as _on_dedicated_ip
from src.core.config import AppConfig
from src.core.constants import DEDICATED_IP_PREFIX
from src.core.enums import (
    Currency,
    DedicatedIpCountry,
    PaymentGatewayType,
    PlanType,
    PurchaseType,
    TransactionStatus,
)
from src.core.metrics import DEDICATED_IP_CHOSEN_TOTAL, DEDICATED_IP_OFFERED_TOTAL
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.models import (
    BillingPlan,
    BillingPlanDuration,
    BillingPlanSnapshot,
    BillingPriceDetails,
    BillingSubscription,
)
from src.infrastructure.taskiq.tasks.redirects import redirect_to_successed_payment_task
from src.infrastructure.taskiq.tasks.subscriptions import purchase_subscription_task
from src.models.dto import PlanSnapshotDto, PriceDetailsDto, TransactionDto
from src.services.dedicated_ip import (
    DEDUP_KEY,
    KIND,
    get_choice,
    is_ultra_tag,
    is_ultra_user,
    offer_country_choice,
)
from src.services.notification import NotificationService
from src.services.ops_notify import post_ops_event
from tests.conftest import (
    make_dialog_manager,
    make_i18n,
    make_subscription,
    make_user,
    unwrap_inject,
)
from tests.reminder_fakes import FakeBilling
from tests.test_api_client import _make_provision_result, unwrap_task

TG = 4242
REF = (TG, KIND, DEDUP_KEY)


def _ultra_billing_subscription(*, tag="ULTRA", trial=False, sub_id=901):
    return BillingSubscription(
        ID=sub_id,
        UserTelegramID=TG,
        Status="ACTIVE",
        IsTrial=trial,
        Plan=BillingPlanSnapshot(id=38, name="👑 Ультра", tag=tag),
    )


class Billing(FakeBilling):
    def __init__(self, subscription=None) -> None:
        super().__init__()
        self.current_subscriptions[TG] = subscription


def _user(telegram_id=TG, username="anna"):
    user = make_user(telegram_id=telegram_id)
    object.__setattr__(user, "username", username)
    return user


def _redis(locked=False):
    redis = AsyncMock()
    redis.set.return_value = None if locked else True
    return redis


def _callback(data):
    callback = MagicMock()
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    callback.message.edit_reply_markup = AsyncMock()
    return callback


def _config(url="http://notify.test", token="tok"):
    config = MagicMock()
    config.notify_url = url
    config.notify_token = SecretStr(token)
    return config


def _translator():
    hub = TranslatorHub(
        {"ru": ("ru",)},
        root_locale="ru",
        storage=FileStorage(path=Path("assets/translations") / "{locale}"),
    )
    return hub.get_translator_by_locale("ru")


def _ultra_snapshot(tag="ULTRA"):
    return PlanSnapshotDto(
        id=38,
        name="👑 Ультра",
        tag=tag,
        type=PlanType.BOTH,
        traffic_limit=1024,
        device_limit=20,
        duration=30,
        traffic_limit_strategy=TrafficLimitStrategy.MONTH,
        internal_squads=[],
        external_squad=None,
    )


def _ultra_user_subscription(*, tag="ULTRA", active=True, trial=False):
    subscription = make_subscription(plan_id=38, plan_name="👑 Ультра", active=active)
    object.__setattr__(subscription, "plan", _ultra_snapshot(tag))
    object.__setattr__(subscription, "is_trial", trial)
    return subscription


class TestUltraDetection:
    @pytest.mark.parametrize("tag", ["ULTRA", "ultra", " Ultra "])
    def test_tag_matches_in_any_case(self, tag):
        assert is_ultra_tag(tag) is True

    @pytest.mark.parametrize("tag", [None, "", "MAX", "ULTRA2"])
    def test_other_tags_do_not_match(self, tag):
        assert is_ultra_tag(tag) is False

    def test_active_paid_ultra_user(self):
        assert is_ultra_user(make_user(subscription=_ultra_user_subscription())) is True

    def test_expired_trial_or_other_plan_is_not_ultra(self):
        assert (
            is_ultra_user(make_user(subscription=_ultra_user_subscription(active=False))) is False
        )
        assert is_ultra_user(make_user(subscription=_ultra_user_subscription(trial=True))) is False
        assert is_ultra_user(make_user(subscription=_ultra_user_subscription(tag=None))) is False
        assert is_ultra_user(make_user()) is False


class TestKeyboard:
    def test_offers_sweden_and_netherlands_only(self):
        rows = get_dedicated_ip_keyboard().inline_keyboard

        assert [len(row) for row in rows] == [1, 1]
        assert [row[0].callback_data for row in rows] == [
            f"{DEDICATED_IP_PREFIX}{code}" for code in ("SE", "NL")
        ]
        assert [row[0].text for row in rows] == [
            "btn-dedicated-ip-se",
            "btn-dedicated-ip-nl",
        ]

    def test_codes_fit_the_billing_answer_pattern(self):
        for country in DedicatedIpCountry:
            assert re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}", country.value)


class TestOffer:
    async def test_ultra_purchase_sends_the_prompt_with_two_buttons(self):
        billing = Billing()
        ntf = AsyncMock()
        before = DEDICATED_IP_OFFERED_TOTAL._value.get()

        sent = await offer_country_choice(
            user=_user(), plan_tag="ULTRA", billing=billing, notification_service=ntf
        )

        assert sent is True
        payload = ntf.notify_user.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-dedicated-ip-offer"
        assert payload.auto_delete_after is None
        buttons = [b for row in payload.reply_markup.inline_keyboard for b in row]
        assert len(buttons) == 2
        assert REF in billing.claims
        assert DEDICATED_IP_OFFERED_TOTAL._value.get() == before + 1

    @pytest.mark.parametrize("tag", [None, "", "MAX"])
    async def test_other_plans_get_nothing(self, tag):
        billing = Billing()
        ntf = AsyncMock()

        sent = await offer_country_choice(
            user=_user(), plan_tag=tag, billing=billing, notification_service=ntf
        )

        assert sent is False
        ntf.notify_user.assert_not_called()
        assert billing.claims == {}

    async def test_renewal_with_a_saved_choice_is_not_asked_again(self):
        billing = Billing()
        billing.claims[REF] = "SE"
        ntf = AsyncMock()

        sent = await offer_country_choice(
            user=_user(), plan_tag="ULTRA", billing=billing, notification_service=ntf
        )

        assert sent is False
        ntf.notify_user.assert_not_called()
        assert billing.claims[REF] == "SE"

    async def test_renewal_without_a_choice_asks_again(self):
        billing = Billing()
        billing.claims[REF] = None
        ntf = AsyncMock()

        sent = await offer_country_choice(
            user=_user(), plan_tag="ULTRA", billing=billing, notification_service=ntf
        )

        assert sent is True
        ntf.notify_user.assert_awaited_once()

    async def test_blocked_bot_counts_as_not_sent(self):
        billing = Billing()
        ntf = AsyncMock()
        ntf.notify_user.return_value = None

        sent = await offer_country_choice(
            user=_user(), plan_tag="ULTRA", billing=billing, notification_service=ntf
        )

        assert sent is False

    async def test_failures_never_raise(self):
        billing = Billing()
        billing.claim_error = RuntimeError("billing down")
        ntf = AsyncMock()

        sent = await offer_country_choice(
            user=_user(), plan_tag="ULTRA", billing=billing, notification_service=ntf
        )
        assert sent is False

        billing.claim_error = None
        ntf.notify_user.side_effect = TelegramNetworkError(method=MagicMock(), message="down")
        sent = await offer_country_choice(
            user=_user(), plan_tag="ULTRA", billing=billing, notification_service=ntf
        )
        assert sent is False


class TestGetChoice:
    async def test_returns_the_saved_country(self):
        billing = Billing()
        billing.claims[REF] = "NL"
        assert await get_choice(billing, TG) is DedicatedIpCountry.NL

    async def test_no_row_or_no_answer_is_none(self):
        billing = Billing()
        assert await get_choice(billing, TG) is None
        billing.claims[REF] = None
        assert await get_choice(billing, TG) is None

    async def test_unknown_answer_is_none(self):
        billing = Billing()
        billing.claims[REF] = "XX"
        assert await get_choice(billing, TG) is None

    async def test_other_users_and_kinds_are_ignored(self):
        billing = Billing()
        billing.claims[(TG + 1, KIND, DEDUP_KEY)] = "LT"
        billing.claims[(TG, "SOURCE_SURVEY", "v1")] = "LT"
        assert await get_choice(billing, TG) is None


def _redirect_setup():
    order: list[str] = []
    bg = MagicMock()

    async def started(*args, **kwargs):
        order.append("payment_message")

    bg.start = AsyncMock(side_effect=started)
    factory = MagicMock()
    factory.bg.return_value = bg
    ntf = AsyncMock()

    async def sent(*args, **kwargs):
        order.append(kwargs["payload"].i18n_key)
        return MagicMock()

    ntf.notify_user.side_effect = sent
    return order, factory, ntf


async def _run_redirect(user, purchase_type, factory, billing, ntf, **extra):
    deps = {
        Bot: MagicMock(),
        BgManagerFactory: factory,
        BillingClient: billing,
        NotificationService: ntf,
    }
    container = AsyncMock()
    container.get.side_effect = lambda dependency, **kwargs: deps[dependency]
    await redirect_to_successed_payment_task.original_func(
        user=user, purchase_type=purchase_type, dishka_container=container, **extra
    )


class TestPaymentSuccessRedirect:
    @pytest.mark.parametrize("purchase_type", [PurchaseType.NEW, PurchaseType.CHANGE])
    async def test_new_and_upgrade_to_ultra_ask_for_the_country_after_the_success_screen(
        self, purchase_type
    ):
        order, factory, ntf = _redirect_setup()
        billing = Billing()
        billing.get_referral_by_referred = AsyncMock(return_value=SimpleNamespace(x=1))

        await _run_redirect(_user(), purchase_type, factory, billing, ntf, plan_tag="ULTRA")

        assert order == ["payment_message", "ntf-dedicated-ip-offer"]

    async def test_renewal_with_a_choice_asks_nothing(self):
        order, factory, ntf = _redirect_setup()
        billing = Billing()
        billing.claims[REF] = "LT"
        billing.get_referral_by_referred = AsyncMock(return_value=SimpleNamespace(x=1))

        await _run_redirect(_user(), PurchaseType.RENEW, factory, billing, ntf, plan_tag="ULTRA")

        assert order == ["payment_message"]

    async def test_other_plans_are_untouched(self):
        order, factory, ntf = _redirect_setup()
        billing = Billing()
        billing.get_referral_by_referred = AsyncMock(return_value=SimpleNamespace(x=1))

        await _run_redirect(_user(), PurchaseType.NEW, factory, billing, ntf)

        assert order == ["payment_message"]
        assert billing.claims == {}

    async def test_failing_offer_keeps_the_success_screen(self):
        order, factory, ntf = _redirect_setup()
        ntf.notify_user.side_effect = RuntimeError("telegram down")
        billing = Billing()
        billing.get_referral_by_referred = AsyncMock(return_value=SimpleNamespace(x=1))

        await _run_redirect(_user(), PurchaseType.NEW, factory, billing, ntf, plan_tag="ULTRA")

        assert order == ["payment_message"]


def _transaction(plan, purchase_type=PurchaseType.NEW):
    return TransactionDto(
        payment_id=uuid4(),
        status=TransactionStatus.COMPLETED,
        purchase_type=purchase_type,
        gateway_type=PaymentGatewayType.YOOKASSA,
        pricing=PriceDetailsDto(),
        currency=Currency.RUB,
        plan=plan,
        user=make_user(telegram_id=777),
    )


async def _run_purchase(plan):
    config = MagicMock()
    config.remnawave.sub_public_domain = "getfastlink.online"
    config.website_url = "https://componovpn.com"
    api_client = AsyncMock()
    api_client.provision_user.return_value = _make_provision_result()
    subscription_service = AsyncMock()
    subscription_service.get_current.return_value = None
    raw_fn = unwrap_task(purchase_subscription_task)

    with patch(
        "src.infrastructure.taskiq.tasks.subscriptions.redirect_to_successed_payment_task",
    ) as redirect:
        redirect.kiq = AsyncMock()
        await raw_fn(
            transaction=_transaction(plan),
            subscription=None,
            config=config,
            api_client=api_client,
            remnawave_service=AsyncMock(),
            subscription_service=subscription_service,
            transaction_service=AsyncMock(),
            notification_service=AsyncMock(),
            referral_service=AsyncMock(),
            redis_client=AsyncMock(),
        )
    return redirect.kiq


class TestPurchaseTaskPassesThePlanTag:
    async def test_ultra_purchase_hands_the_tag_to_the_redirect(self):
        kiq = await _run_purchase(_ultra_snapshot())

        kiq.assert_awaited_once()
        assert kiq.await_args.args[1] is PurchaseType.NEW
        assert kiq.await_args.kwargs == {"plan_tag": "ULTRA"}

    async def test_other_plans_keep_the_old_call_shape(self):
        kiq = await _run_purchase(_ultra_snapshot(tag="MAX"))

        kiq.assert_awaited_once()
        assert kiq.await_args.kwargs == {}


class TestCountryCallback:
    async def test_choice_is_stored_confirmed_and_sent_to_the_ops_channel(self):
        billing = Billing(_ultra_billing_subscription())
        billing.claims[REF] = None
        callback = _callback(f"{DEDICATED_IP_PREFIX}LT")
        before = DEDICATED_IP_CHOSEN_TOTAL.labels(country="LT")._value.get()

        with patch.object(dedicated_ip_router, "post_ops_event", new=AsyncMock()) as post:
            raw = unwrap_inject(on_dedicated_ip_country)
            await raw(callback, _user(), make_i18n(), billing, _redis(), _config())

        assert billing.claims[REF] == "LT"
        callback.message.edit_text.assert_awaited_once_with(
            text="[ntf-dedicated-ip-accepted]", reply_markup=None
        )
        assert DEDICATED_IP_CHOSEN_TOTAL.labels(country="LT")._value.get() == before + 1
        post.assert_awaited_once()
        details = post.await_args.kwargs["details"]
        assert details == {
            "telegram_id": TG,
            "username": "@anna",
            "subscription_id": 901,
            "country": "LT",
            "command": f"tools/compono-dedicated-ip.sh add {TG} LT",
        }

    @pytest.mark.parametrize("code", ["LT", "SE", "NL"])
    async def test_every_country_builds_the_provisioning_command(self, code):
        assert provision_command(TG, DedicatedIpCountry(code)) == (
            f"tools/compono-dedicated-ip.sh add {TG} {code}"
        )

    async def test_user_without_username_is_marked_none(self):
        billing = Billing(_ultra_billing_subscription())
        billing.claims[REF] = None

        with patch.object(dedicated_ip_router, "post_ops_event", new=AsyncMock()) as post:
            raw = unwrap_inject(on_dedicated_ip_country)
            await raw(
                _callback(f"{DEDICATED_IP_PREFIX}SE"),
                _user(username=None),
                make_i18n(),
                billing,
                _redis(),
                _config(),
            )

        assert post.await_args.kwargs["details"]["username"] == "none"

    async def test_pick_without_a_prompt_row_still_saves(self):
        billing = Billing(_ultra_billing_subscription())
        callback = _callback(f"{DEDICATED_IP_PREFIX}NL")

        with patch.object(dedicated_ip_router, "post_ops_event", new=AsyncMock()):
            raw = unwrap_inject(on_dedicated_ip_country)
            await raw(callback, _user(), make_i18n(), billing, _redis(), _config())

        assert billing.claims[REF] == "NL"

    async def test_second_choice_does_not_overwrite_or_notify_again(self):
        billing = Billing(_ultra_billing_subscription())
        billing.claims[REF] = "LT"
        callback = _callback(f"{DEDICATED_IP_PREFIX}SE")

        with patch.object(dedicated_ip_router, "post_ops_event", new=AsyncMock()) as post:
            raw = unwrap_inject(on_dedicated_ip_country)
            await raw(callback, _user(), make_i18n(), billing, _redis(), _config())

        assert billing.claims[REF] == "LT"
        post.assert_not_called()
        callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
        callback.answer.assert_awaited_once_with(text="[msg-dedicated-ip-already]")

    async def test_double_tap_is_collapsed(self):
        billing = Billing(_ultra_billing_subscription())
        billing.claims[REF] = None
        callback = _callback(f"{DEDICATED_IP_PREFIX}SE")

        with patch.object(dedicated_ip_router, "post_ops_event", new=AsyncMock()) as post:
            raw = unwrap_inject(on_dedicated_ip_country)
            await raw(callback, _user(), make_i18n(), billing, _redis(locked=True), _config())

        assert billing.claims[REF] is None
        post.assert_not_called()

    @pytest.mark.parametrize(
        "subscription",
        [None, _ultra_billing_subscription(tag="MAX"), _ultra_billing_subscription(trial=True)],
    )
    async def test_user_without_active_ultra_is_refused(self, subscription):
        billing = Billing(subscription)
        callback = _callback(f"{DEDICATED_IP_PREFIX}LT")

        with patch.object(dedicated_ip_router, "post_ops_event", new=AsyncMock()) as post:
            raw = unwrap_inject(on_dedicated_ip_country)
            await raw(callback, _user(), make_i18n(), billing, _redis(), _config())

        assert billing.claims == {}
        post.assert_not_called()
        callback.answer.assert_awaited_once_with(
            text="[msg-dedicated-ip-not-ultra]", show_alert=True
        )

    async def test_unknown_country_is_ignored(self):
        billing = Billing(_ultra_billing_subscription())
        callback = _callback(f"{DEDICATED_IP_PREFIX}XX")

        raw = unwrap_inject(on_dedicated_ip_country)
        await raw(callback, _user(), make_i18n(), billing, _redis(), _config())

        callback.message.edit_text.assert_not_called()
        callback.answer.assert_awaited_once_with()

    async def test_billing_error_releases_the_lock_and_does_not_crash(self):
        billing = Billing(_ultra_billing_subscription())
        billing.answer_user_reminder = AsyncMock(side_effect=RuntimeError("billing down"))
        redis = _redis()
        callback = _callback(f"{DEDICATED_IP_PREFIX}LT")

        with patch.object(dedicated_ip_router, "post_ops_event", new=AsyncMock()) as post:
            raw = unwrap_inject(on_dedicated_ip_country)
            await raw(callback, _user(), make_i18n(), billing, redis, _config())

        callback.message.edit_text.assert_not_called()
        post.assert_not_called()
        redis.delete.assert_awaited_once()

    async def test_failed_ops_post_does_not_lose_the_choice(self):
        billing = Billing(_ultra_billing_subscription())
        billing.claims[REF] = None
        callback = _callback(f"{DEDICATED_IP_PREFIX}LT")

        with patch.object(dedicated_ip_router, "post_ops_event", new=AsyncMock(return_value=False)):
            raw = unwrap_inject(on_dedicated_ip_country)
            await raw(callback, _user(), make_i18n(), billing, _redis(), _config())

        assert billing.claims[REF] == "LT"
        callback.message.edit_text.assert_awaited_once()


class TestOpsNotify:
    @staticmethod
    def _client(status=202, error=None):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        if error:
            client.post.side_effect = error
        else:
            client.post.return_value = SimpleNamespace(status_code=status, text="x")
        return client

    async def test_posts_a_card_with_the_bearer_token(self):
        client = self._client()
        with patch("src.services.ops_notify.httpx.AsyncClient", return_value=client):
            ok = await post_ops_event(
                _config("http://notify.test/"),
                title="t",
                summary="s",
                details={"a": 1},
                key="k",
            )

        assert ok is True
        args, kwargs = client.post.await_args
        assert args == ("http://notify.test/v1/event",)
        assert kwargs["headers"] == {"Authorization": "Bearer tok"}
        assert kwargs["json"] == {
            "kind": "info",
            "severity": "info",
            "title": "t",
            "summary": "s",
            "details": {"a": 1},
            "topic": "general",
            "key": "k",
        }

    @pytest.mark.parametrize("url,token", [("", "tok"), ("http://notify.test", "")])
    async def test_unconfigured_sends_nothing(self, url, token):
        with patch("src.services.ops_notify.httpx.AsyncClient") as factory:
            ok = await post_ops_event(_config(url, token), title="t", summary="s", details={})

        assert ok is False
        factory.assert_not_called()

    async def test_http_errors_return_false(self):
        client = self._client(error=httpx.ConnectError("down"))
        with patch("src.services.ops_notify.httpx.AsyncClient", return_value=client):
            assert await post_ops_event(_config(), title="t", summary="s", details={}) is False

        client = self._client(status=401)
        with patch("src.services.ops_notify.httpx.AsyncClient", return_value=client):
            assert await post_ops_event(_config(), title="t", summary="s", details={}) is False

    def test_config_defaults_to_disabled(self):
        assert AppConfig.model_fields["notify_url"].default == ""
        assert AppConfig.model_fields["notify_token"].default.get_secret_value() == ""


class TestSubscriptionScreen:
    async def test_getter_flags_ultra_users_only(self):
        getter = unwrap_inject(_subscription_getter)
        remnawave = AsyncMock()
        billing = AsyncMock()
        billing.get_trial_plan.return_value = None

        async def flag(user):
            data = await getter(
                dialog_manager=make_dialog_manager(),
                user=user,
                billing=billing,
                remnawave_service=remnawave,
            )
            return data["is_ultra"]

        assert await flag(make_user(subscription=_ultra_user_subscription())) is True
        assert await flag(make_user(subscription=make_subscription())) is False
        assert await flag(make_user()) is False

    def test_window_has_a_dedicated_ip_button_for_ultra_only(self):
        buttons = [
            widget
            for row in subscription_window.keyboard.buttons
            for widget in getattr(row, "buttons", [row])
            if getattr(widget, "widget_id", None) == "dedicated_ip"
        ]
        assert len(buttons) == 1
        shown = buttons[0].is_({"is_ultra": True}, MagicMock())
        hidden = buttons[0].is_({"is_ultra": False}, MagicMock())
        assert (shown, hidden) == (True, False)

    async def test_button_shows_the_saved_country(self):
        handler = unwrap_inject(_on_dedicated_ip)
        billing = Billing()
        billing.claims[REF] = "SE"
        ntf = AsyncMock()
        dm = make_dialog_manager()
        dm.middleware_data["user"] = _user()

        await handler(MagicMock(), MagicMock(), dm, billing, ntf)

        payload = ntf.notify_user.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-dedicated-ip-current"
        assert payload.i18n_kwargs == {"country": "SE"}
        assert payload.reply_markup is None

    async def test_button_lets_the_user_pick_when_nothing_is_saved(self):
        handler = unwrap_inject(_on_dedicated_ip)
        billing = Billing()
        ntf = AsyncMock()
        dm = make_dialog_manager()
        dm.middleware_data["user"] = _user()

        await handler(MagicMock(), MagicMock(), dm, billing, ntf)

        payload = ntf.notify_user.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-dedicated-ip-pick"
        assert len(payload.reply_markup.inline_keyboard) == 2
        assert REF in billing.claims

    async def test_button_survives_billing_errors(self):
        handler = unwrap_inject(_on_dedicated_ip)
        billing = Billing()
        billing.list_user_reminders = AsyncMock(side_effect=RuntimeError("billing down"))
        ntf = AsyncMock()
        dm = make_dialog_manager()
        dm.middleware_data["user"] = _user()

        await handler(MagicMock(), MagicMock(), dm, billing, ntf)

        ntf.notify_user.assert_not_called()


class TestTranslations:
    def test_prompt_and_reply_texts_are_exact(self):
        i18n = _translator()
        assert i18n.get("ntf-dedicated-ip-offer") == (
            "🎉 Тариф Ультра активирован! Выберите страну для вашего выделенного IP:"
        )
        assert i18n.get("ntf-dedicated-ip-accepted") == (
            "Принято! Настроим ваш выделенный IP в течение 24 часов "
            "и напишем вам, что нажать в Happ."
        )

    def test_button_labels(self):
        i18n = _translator()
        assert i18n.get("btn-dedicated-ip-lt") == "🇱🇹 Литва"
        assert i18n.get("btn-dedicated-ip-se") == "🇸🇪 Швеция"
        assert i18n.get("btn-dedicated-ip-nl") == "🇳🇱 Нидерланды"
        assert i18n.get("btn-subscription-dedicated-ip") == "🌐 Выделенный IP"

    @pytest.mark.parametrize(
        "code,label", [("LT", "Литва"), ("SE", "Швеция"), ("NL", "Нидерланды")]
    )
    def test_saved_country_renders(self, code, label):
        i18n = _translator()
        assert label in i18n.get("ntf-dedicated-ip-current", country=code)
        assert label in i18n.get("msg-dedicated-ip-already", country=code)


def _billing_plan(plan_id, name, gb, devices, tag=None):
    return BillingPlan(
        ID=plan_id,
        Name=name,
        Tag=tag,
        Type="BOTH",
        IsActive=True,
        TrafficLimit=gb,
        DeviceLimit=devices,
        Durations=[BillingPlanDuration(ID=plan_id * 10, Days=30)],
    )


class TestFourthPlanOnThePlanScreen:
    async def test_four_paid_plans_render_in_billing_order(self):
        prices = {1: "119", 2: "239", 3: "499", 38: "799"}
        billing = AsyncMock()
        billing.get_available_plans.return_value = [
            _billing_plan(1, "⚡️ Старт", 100, 2),
            _billing_plan(2, "🚀 Про", 300, 6),
            _billing_plan(3, "💎 Макс", 1024, 20),
            _billing_plan(38, "👑 Ультра", 1024, 20, tag="ULTRA"),
        ]
        billing.get_default_currency.return_value = "RUB"

        async def calculate(telegram_id, plan_id, duration_days, currency, **kwargs):
            return BillingPriceDetails(
                original_amount=prices[plan_id],
                discount_percent=0,
                final_amount=prices[plan_id],
            )

        billing.calculate_price.side_effect = calculate

        data = await unwrap_inject(_plans_getter)(
            dialog_manager=make_dialog_manager(),
            user=make_user(),
            i18n=_translator(),
            billing=billing,
        )

        assert [p["id"] for p in data["plans"]] == [1, 2, 3, 38]
        assert data["plans"][3]["name"] == "👑 Ультра"
        lines = [re.sub(r"\s", " ", line) for line in data["summary"].split("\n")]
        assert lines[2] == "💎 Макс — 499 ₽/мес · 1 024 ГБ, 20 устройств"
        assert lines[3] == "👑 Ультра — 799 ₽/мес · 1 024 ГБ, 20 устройств, 🌐 личный IP (Швеция или Нидерланды)"
