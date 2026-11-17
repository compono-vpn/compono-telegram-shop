"""TV pairing in the bot (COM-202): /start tv-<CODE>, the confirm/cancel buttons, and the
compono-api claim client."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from fluentogram import TranslatorHub
from fluentogram.storage import FileStorage
from loguru import logger

from src.bot.routers.extra.tv_pair import on_tv_pair_cancel, on_tv_pair_confirm
from src.bot.routers.menu.handlers import _is_tv_pair_start, on_tv_pair_start_command
from src.bot.states import Subscription
from src.core.constants import (
    AFFILIATE_PREFIX,
    ENCRYPTED_PREFIX,
    GOTO_PREFIX,
    PURCHASE_PREFIX,
    REFERRAL_PREFIX,
    REMNASHOP_PREFIX,
    SOURCE_PREFIX,
    TV_PAIR_CANCEL,
    TV_PAIR_CONFIRM_PREFIX,
    TV_PAIR_PREFIX,
)
from src.core.metrics import TV_PAIR_TOTAL
from src.core.utils.attribution import decode_start_param, source_line_for_start, source_tag
from src.infrastructure.api.client import ApiClient, TvPairClaim
from src.services.tv_pair import (
    code_from_callback,
    code_from_start_param,
    code_from_start_text,
    confirm_keyboard,
    display_code,
    log_code,
    retry_keyboard,
)
from tests.conftest import make_dialog_manager, make_i18n, make_user, unwrap_inject

CODE = "K7M4QX9P"
TG = 1750352084


# --------------------------------------------------------------------- parsing


class TestStartPayload:
    @pytest.mark.parametrize(
        "param,expected",
        [
            ("tv-K7M4QX9P", "K7M4QX9P"),
            ("tv-k7m4qx9p", "K7M4QX9P"),
            ("TV-K7M4QX9P", "K7M4QX9P"),
            ("tv-00000000", "00000000"),
            ("tv-ZZZZZZZZ", "ZZZZZZZZ"),
            (" tv-K7M4QX9P ", "K7M4QX9P"),
        ],
    )
    def test_valid(self, param, expected):
        assert code_from_start_param(param) == expected

    @pytest.mark.parametrize(
        "param",
        [
            None,
            "",
            "tv-",
            "tv-K7M4QX9",  # 7
            "tv-K7M4QX9PA",  # 9
            "tv-K7M4-QX9P",  # the deep link never carries the dash
            "tv-K7M4QX9I",  # I/L/O/U are not Crockford
            "tv-K7M4QX9L",
            "tv-K7M4QX9O",
            "tv-K7M4QX9U",
            "tv_K7M4QX9P",
            "tvK7M4QX9P",
            "K7M4QX9P",
            "source-tv-K7M4QX9P",
            "tv-K7M4QX9П",
        ],
    )
    def test_invalid(self, param):
        assert code_from_start_param(param) is None

    @pytest.mark.parametrize(
        "param",
        [
            "source-a1_site-header_lios_ry",
            "source-home-hero",
            "source-channel_proxy",
            "ref_abc123",
            "aff-42",
            "web_tok",
            "proxy",
            "beta_testers",
            f"{REMNASHOP_PREFIX}x",
            f"{PURCHASE_PREFIX}x",
            f"{GOTO_PREFIX}x",
            f"{ENCRYPTED_PREFIX}x",
        ],
    )
    def test_other_payloads_are_not_tv(self, param):
        assert code_from_start_param(param) is None
        assert code_from_start_text(f"/start {param}") is None

    def test_prefix_collides_with_no_existing_payload(self):
        for prefix in (
            SOURCE_PREFIX,
            REFERRAL_PREFIX,
            AFFILIATE_PREFIX,
            REMNASHOP_PREFIX,
            PURCHASE_PREFIX,
            GOTO_PREFIX,
            ENCRYPTED_PREFIX,
            "web_",
            "proxy",
            "beta_testers",
        ):
            assert not prefix.startswith(TV_PAIR_PREFIX)
            assert not TV_PAIR_PREFIX.startswith(prefix)

    def test_deep_link_fits_telegram_rules(self):
        payload = f"{TV_PAIR_PREFIX}{CODE}"
        assert len(payload) == 11
        assert all(c.isalnum() or c in "_-" for c in payload)


class TestAttributionIsUntouched:
    """A tv- payload is not attribution: new users get source None, the admin card says
    "Прямой заход", and source- payloads still decode exactly as before."""

    def test_tv_payload_decodes_to_nothing(self):
        assert decode_start_param(f"tv-{CODE}") is None
        assert source_tag(decode_start_param(f"tv-{CODE}")) is None
        assert source_line_for_start(f"tv-{CODE}") == source_line_for_start(None)

    def test_source_payloads_still_decode(self):
        legacy = decode_start_param("source-home-hero")
        assert legacy is not None and legacy.version == 0 and legacy.slot == "home-hero"
        v1 = decode_start_param("source-a1_site-header_lios_ry")
        assert v1 is not None and v1.version == 1 and v1.slot == "site-header"


class TestStartText:
    @pytest.mark.parametrize(
        "text",
        [
            f"/start tv-{CODE}",
            f"/start tv-{CODE.lower()}",
            f"/START tv-{CODE}",
            f"/start@compono_bot tv-{CODE}",
            f"/start  tv-{CODE}  ",
        ],
    )
    def test_matches(self, text):
        assert code_from_start_text(text) == CODE
        message = MagicMock(spec=Message)
        message.text = text
        assert _is_tv_pair_start(message)

    @pytest.mark.parametrize(
        "text",
        [
            None,
            "",
            "/start",
            f"tv-{CODE}",
            f"/start tv-{CODE} extra",
            f"/start source-x tv-{CODE}",
            f"/startx tv-{CODE}",
            f"/start tv-{CODE[:7]}",
            "/start beta_testers",
        ],
    )
    def test_does_not_match(self, text):
        assert code_from_start_text(text) is None
        message = MagicMock(spec=Message)
        message.text = text
        assert not _is_tv_pair_start(message)


class TestCallbackData:
    def test_round_trip(self):
        kb = confirm_keyboard(CODE, "ok", "no")
        confirm, cancel = kb.inline_keyboard[0][0], kb.inline_keyboard[1][0]
        assert confirm.callback_data == f"{TV_PAIR_CONFIRM_PREFIX}{CODE}"
        assert cancel.callback_data == TV_PAIR_CANCEL
        assert code_from_callback(confirm.callback_data) == CODE
        assert len(confirm.callback_data.encode()) <= 64
        retry = retry_keyboard(CODE, "again").inline_keyboard[0][0]
        assert code_from_callback(retry.callback_data) == CODE

    @pytest.mark.parametrize(
        "data",
        [None, "", "tvp:", "tvp:k7m4qx9p", "tvp:K7M4QX9", "tvp:K7M4QX9I", "tvp:K7M4QX9P;rm", "tvx"],
    )
    def test_forged_or_malformed(self, data):
        assert code_from_callback(data) is None

    def test_display_and_log(self):
        assert display_code(CODE) == "K7M4-QX9P"
        assert log_code(CODE) == "K7******"
        assert CODE[2:] not in log_code(CODE)


# --------------------------------------------------------------------- api client


def _client(handler) -> ApiClient:
    client = ApiClient(base_url="http://api.test", internal_secret="s3cret")
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers=client._headers()
    )
    return client


class TestClaimClient:
    async def test_sends_contract_request(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["url"] = str(request.url)
            seen["secret"] = request.headers.get("X-Internal-Secret")
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200, json={"status": "attached", "expiresAt": "2026-12-01T10:10:00Z"}
            )

        result = await _client(handler).claim_tv_pair(CODE, TG)
        assert result is TvPairClaim.ATTACHED
        assert seen == {
            "method": "POST",
            "url": "http://api.test/api/v1/internal/tv-pair/claim",
            "secret": "s3cret",
            "body": {"code": CODE, "telegramId": TG},
        }

    @pytest.mark.parametrize(
        "status,error,expected",
        [
            (404, "code_not_found", TvPairClaim.NOT_FOUND),
            (409, "code_already_claimed", TvPairClaim.ALREADY_CLAIMED),
            (422, "no_active_subscription", TvPairClaim.NO_SUBSCRIPTION),
            (429, "rate_limited", TvPairClaim.RATE_LIMITED),
            (400, "invalid_request", TvPairClaim.FAILED),
            (401, "unauthorized", TvPairClaim.FAILED),
            (500, "boom", TvPairClaim.FAILED),
            (502, "billing_unavailable", TvPairClaim.FAILED),
            (503, "pairing_unavailable", TvPairClaim.FAILED),
        ],
    )
    async def test_status_mapping(self, status, error, expected):
        result = await _client(
            lambda r: httpx.Response(status, json={"error": error})
        ).claim_tv_pair(CODE, TG)
        assert result is expected

    async def test_non_json_error_body(self):
        result = await _client(
            lambda r: httpx.Response(502, text="<html>bad gateway</html>")
        ).claim_tv_pair(CODE, TG)
        assert result is TvPairClaim.FAILED

    async def test_network_error_is_failed_not_raised(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        assert await _client(handler).claim_tv_pair(CODE, TG) is TvPairClaim.FAILED

    async def test_logs_never_carry_the_code_and_expected_answers_are_not_errors(self):
        lines: list[tuple[str, str]] = []
        sink = logger.add(lambda m: lines.append((m.record["level"].name, m.record["message"])))
        try:
            await _client(
                lambda r: httpx.Response(404, json={"error": "code_not_found"})
            ).claim_tv_pair(CODE, TG)
            await _client(
                lambda r: httpx.Response(503, json={"error": "pairing_unavailable"})
            ).claim_tv_pair(CODE, TG)
        finally:
            logger.remove(sink)
        assert lines, "the client logs its answers"
        assert all(CODE not in msg for _, msg in lines)
        levels = [lvl for lvl, msg in lines if "tv-pair" in msg]
        assert levels == ["INFO", "ERROR"], "404 is a normal answer, 503 is an error"


# --------------------------------------------------------------------- handlers


def _metric(result: str) -> float:
    return TV_PAIR_TOTAL.labels(result=result)._value.get()


class TestStartHandler:
    async def test_asks_before_claiming(self):
        message = MagicMock()
        message.text = f"/start tv-{CODE.lower()}"
        message.answer = AsyncMock()
        i18n = make_i18n()
        before = _metric("offered")

        await unwrap_inject(on_tv_pair_start_command)(message=message, user=make_user(), i18n=i18n)

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        assert text == "[msg-tv-pair-confirm]"
        i18n.get.assert_any_call("msg-tv-pair-confirm", code="K7M4-QX9P")
        markup = message.answer.await_args.kwargs["reply_markup"]
        assert markup.inline_keyboard[0][0].callback_data == f"tvp:{CODE}"
        assert markup.inline_keyboard[1][0].callback_data == "tvx"
        assert _metric("offered") == before + 1

    async def test_does_not_call_the_api_on_start(self):
        # The start handler has no API dependency at all: claiming needs a tap.
        import inspect

        params = inspect.signature(unwrap_inject(on_tv_pair_start_command)).parameters
        assert "api_client" not in params


def _callback(data: str):
    callback = MagicMock()
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    return callback


async def _confirm(result: TvPairClaim | None, data: str = f"tvp:{CODE}"):
    callback = _callback(data)
    api = MagicMock()
    api.claim_tv_pair = AsyncMock(return_value=result)
    dm = make_dialog_manager()
    dm.start = AsyncMock()
    dm.update = AsyncMock()
    i18n = make_i18n()
    user = make_user(telegram_id=TG)
    await unwrap_inject(on_tv_pair_confirm)(
        callback=callback, user=user, dialog_manager=dm, i18n=i18n, api_client=api
    )
    return callback, api, dm, i18n


class TestConfirmHandler:
    async def test_attached(self):
        before = _metric("attached")
        callback, api, dm, _ = await _confirm(TvPairClaim.ATTACHED)
        api.claim_tv_pair.assert_awaited_once_with(CODE, TG)
        callback.message.edit_text.assert_awaited_once_with(
            text="[msg-tv-pair-attached]", reply_markup=None
        )
        callback.answer.assert_awaited_once_with()
        dm.start.assert_not_called()
        assert _metric("attached") == before + 1

    async def test_no_subscription_opens_plans_and_keeps_a_retry(self):
        callback, _, dm, i18n = await _confirm(TvPairClaim.NO_SUBSCRIPTION)
        kwargs = callback.message.edit_text.await_args.kwargs
        assert kwargs["text"] == "[msg-tv-pair-no-subscription]"
        i18n.get.assert_any_call("msg-tv-pair-no-subscription", code="K7M4-QX9P")
        assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data == f"tvp:{CODE}"
        dm.start.assert_awaited_once()
        assert dm.start.await_args.args[0] == Subscription.PLANS

    @pytest.mark.parametrize(
        "result,key",
        [
            (TvPairClaim.NOT_FOUND, "msg-tv-pair-expired"),
            (TvPairClaim.ALREADY_CLAIMED, "msg-tv-pair-used"),
        ],
    )
    async def test_final_answers_remove_the_buttons(self, result, key):
        callback, _, dm, _ = await _confirm(result)
        callback.message.edit_text.assert_awaited_once_with(text=f"[{key}]", reply_markup=None)
        dm.start.assert_not_called()

    @pytest.mark.parametrize(
        "result,key",
        [
            (TvPairClaim.RATE_LIMITED, "msg-tv-pair-rate-limited"),
            (TvPairClaim.FAILED, "msg-tv-pair-failed"),
        ],
    )
    async def test_transient_answers_keep_the_question(self, result, key):
        callback, _, dm, _ = await _confirm(result)
        callback.message.edit_text.assert_not_called()
        callback.answer.assert_awaited_once_with(text=f"[{key}]", show_alert=True)
        dm.start.assert_not_called()

    @pytest.mark.parametrize("data", ["tvp:", "tvp:BAD", "tvp:k7m4qx9p", "tvp:K7M4QX9PZ"])
    async def test_malformed_button_never_calls_the_api(self, data):
        callback, api, _, _ = await _confirm(TvPairClaim.ATTACHED, data=data)
        api.claim_tv_pair.assert_not_called()
        callback.answer.assert_awaited_once_with()

    async def test_claims_for_the_user_who_tapped(self):
        # The Telegram ID sent to the API is the tapping user's, never one from the button.
        callback, api, _, _ = await _confirm(TvPairClaim.ATTACHED)
        assert api.claim_tv_pair.await_args.args == (CODE, TG)


class TestUnchangedEdit:
    """Regression: a repeated tap that leads to the same text and buttons (a second tap on
    «Подключить» while still without a subscription, or a double tap) makes Telegram refuse
    editMessageText with "message is not modified". That must not escape the handler: it would
    reach the error middleware, page admins with #EventError and push the user to the main menu.
    """

    NOT_MODIFIED = (
        "Telegram server says - Bad Request: message is not modified: specified new message "
        "content and reply markup are exactly the same as a current content and reply markup "
        "of the message"
    )

    def _failing_edit(self, message: str):
        return AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message=message))

    @pytest.mark.parametrize("result", [TvPairClaim.ATTACHED, TvPairClaim.NO_SUBSCRIPTION])
    async def test_not_modified_is_ignored_and_the_tap_is_answered(self, monkeypatch, result):
        callback = _callback(f"tvp:{CODE}")
        callback.message.edit_text = self._failing_edit(self.NOT_MODIFIED)
        api = MagicMock()
        api.claim_tv_pair = AsyncMock(return_value=result)
        dm = make_dialog_manager()
        dm.start = AsyncMock()
        dm.update = AsyncMock()
        await unwrap_inject(on_tv_pair_confirm)(
            callback=callback,
            user=make_user(telegram_id=TG),
            dialog_manager=dm,
            i18n=make_i18n(),
            api_client=api,
        )
        callback.message.edit_text.assert_awaited_once()
        callback.answer.assert_awaited_once_with()
        if result is TvPairClaim.NO_SUBSCRIPTION:
            dm.start.assert_awaited_once()

    async def test_cancel_not_modified_is_ignored(self):
        callback = _callback("tvx")
        callback.message.edit_text = self._failing_edit(self.NOT_MODIFIED)
        await unwrap_inject(on_tv_pair_cancel)(
            callback=callback, user=make_user(), i18n=make_i18n()
        )
        callback.answer.assert_awaited_once_with()

    async def test_other_bad_requests_still_raise(self):
        callback = _callback(f"tvp:{CODE}")
        callback.message.edit_text = self._failing_edit("Bad Request: message to edit not found")
        api = MagicMock()
        api.claim_tv_pair = AsyncMock(return_value=TvPairClaim.ATTACHED)
        with pytest.raises(TelegramBadRequest):
            await unwrap_inject(on_tv_pair_confirm)(
                callback=callback,
                user=make_user(telegram_id=TG),
                dialog_manager=make_dialog_manager(),
                i18n=make_i18n(),
                api_client=api,
            )


class TestCancelHandler:
    async def test_cancel(self):
        callback = _callback("tvx")
        before = _metric("cancelled")
        await unwrap_inject(on_tv_pair_cancel)(
            callback=callback, user=make_user(), i18n=make_i18n()
        )
        callback.message.edit_text.assert_awaited_once_with(
            text="[msg-tv-pair-cancelled]", reply_markup=None
        )
        callback.answer.assert_awaited_once_with()
        assert _metric("cancelled") == before + 1


# --------------------------------------------------------------------- copy


@pytest.fixture
def ru():
    hub = TranslatorHub(
        {"ru": ("ru",)},
        root_locale="ru",
        storage=FileStorage(path=Path("assets/translations") / "{locale}"),
    )
    return hub.get_translator_by_locale("ru")


def _plain(s: str) -> str:
    return s.replace("\u2068", "").replace("\u2069", "")


class TestCopy:
    def test_confirm_text_is_the_contract_text(self, ru):
        text = _plain(ru.get("msg-tv-pair-confirm", code="K7M4-QX9P"))
        assert "Подключить телевизор?" in text
        assert "K7M4-QX9P" in text
        assert "Нажмите, только если этот код сейчас на экране вашего телевизора." in text

    def test_buttons(self, ru):
        assert ru.get("btn-tv-pair-confirm") == "📺 Подключить"
        assert ru.get("btn-tv-pair-cancel") == "Отмена"
        assert ru.get("btn-tv-pair-retry") == "📺 Подключить"

    @pytest.mark.parametrize(
        "key,phrase",
        [
            ("msg-tv-pair-attached", "телевизор подключится через несколько секунд"),
            ("msg-tv-pair-expired", "Код устарел"),
            ("msg-tv-pair-used", "Этот код уже использован"),
            ("msg-tv-pair-rate-limited", "Слишком много попыток, подождите"),
            ("msg-tv-pair-failed", "Не получилось подключить телевизор"),
            ("msg-tv-pair-cancelled", "Отменено"),
        ],
    )
    def test_result_texts(self, ru, key, phrase):
        assert phrase in ru.get(key)

    def test_no_subscription_text_names_the_code_and_no_price(self, ru):
        text = _plain(ru.get("msg-tv-pair-no-subscription", code="K7M4-QX9P"))
        assert "K7M4-QX9P" in text and "10 минут" in text
        assert "₽" not in text  # prices are COM-198's, never typed here

    def test_alert_texts_fit_telegram_limit(self, ru):
        for key in ("msg-tv-pair-rate-limited", "msg-tv-pair-failed"):
            assert len(ru.get(key)) <= 200  # answerCallbackQuery text limit
