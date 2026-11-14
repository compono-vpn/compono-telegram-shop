"""The one-time "how did you find us?" question for users who arrived without a source tag."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import Message

from src.bot.keyboards import get_source_survey_keyboard
from src.bot.routers.extra.source_survey import (
    AwaitingSourceSurveyText,
    on_source_survey_answer,
    on_source_survey_other_text,
)
from src.core.constants import SOURCE_SURVEY_PREFIX
from src.core.enums import SourceSurveyAnswer
from src.core.metrics import SOURCE_SURVEY_ANSWERS_TOTAL, SOURCE_SURVEY_SENT_TOTAL
from src.core.utils.time import datetime_now
from src.services.source_survey import (
    DEDUP_KEY,
    KIND,
    is_eligible,
    offer_source_survey,
    sanitize_free_text,
)
from tests.conftest import make_i18n, make_user, unwrap_inject
from tests.reminder_fakes import FakeBilling

TG = 5151
REF = (TG, KIND, DEDUP_KEY)


def _new_user(*, source=None, age_days: float = 0, telegram_id: int = TG):
    user = make_user(telegram_id=telegram_id)
    object.__setattr__(user, "source", source)
    object.__setattr__(user, "created_at", datetime_now() - timedelta(days=age_days))
    return user


def _redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set.return_value = True
    redis.get.return_value = None
    return redis


def _callback(data: str) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    return callback


def _message(text) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.caption = None
    message.answer = AsyncMock()
    return message


def _sent(answer: str) -> float:
    return SOURCE_SURVEY_ANSWERS_TOTAL.labels(answer=answer)._value.get()


class TestEligibility:
    def test_new_user_without_source_is_eligible(self):
        assert is_eligible(_new_user()) is True

    @pytest.mark.parametrize("source", ["home-hero", "channel_pin", "utm_telegram_paid_comp15"])
    def test_user_with_a_source_tag_is_never_asked(self, source):
        assert is_eligible(_new_user(source=source)) is False

    @pytest.mark.parametrize("source", ["", "   "])
    def test_blank_source_counts_as_no_tag(self, source):
        assert is_eligible(_new_user(source=source)) is True

    def test_old_account_is_not_asked(self):
        assert is_eligible(_new_user(age_days=30)) is False

    def test_unknown_signup_date_is_still_asked(self):
        user = _new_user()
        object.__setattr__(user, "created_at", None)
        assert is_eligible(user) is True


class TestOffer:
    async def test_sends_one_message_with_seven_buttons(self):
        billing = FakeBilling()
        ntf = AsyncMock()
        before = SOURCE_SURVEY_SENT_TOTAL._value.get()

        sent = await offer_source_survey(
            user=_new_user(), billing=billing, notification_service=ntf
        )

        assert sent is True
        ntf.notify_user.assert_awaited_once()
        payload = ntf.notify_user.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-source-survey-prompt"
        buttons = [b for row in payload.reply_markup.inline_keyboard for b in row]
        assert len(buttons) == 7
        assert REF in billing.claims
        assert SOURCE_SURVEY_SENT_TOTAL._value.get() == before + 1

    async def test_asks_only_once_per_user(self):
        billing = FakeBilling()
        ntf = AsyncMock()
        user = _new_user()

        first = await offer_source_survey(user=user, billing=billing, notification_service=ntf)
        second = await offer_source_survey(user=user, billing=billing, notification_service=ntf)

        assert (first, second) == (True, False)
        assert ntf.notify_user.await_count == 1

    async def test_user_with_a_source_tag_gets_nothing(self):
        billing = FakeBilling()
        ntf = AsyncMock()

        sent = await offer_source_survey(
            user=_new_user(source="home-hero"), billing=billing, notification_service=ntf
        )

        assert sent is False
        ntf.notify_user.assert_not_called()
        assert billing.claims == {}

    async def test_billing_failure_never_breaks_the_caller(self):
        billing = FakeBilling()
        billing.claim_error = RuntimeError("billing down")
        ntf = AsyncMock()

        sent = await offer_source_survey(
            user=_new_user(), billing=billing, notification_service=ntf
        )

        assert sent is False
        ntf.notify_user.assert_not_called()

    async def test_failed_send_releases_the_claim_and_does_not_raise(self):
        billing = FakeBilling()
        ntf = AsyncMock()
        ntf.notify_user.side_effect = TelegramNetworkError(method=MagicMock(), message="down")

        sent = await offer_source_survey(
            user=_new_user(), billing=billing, notification_service=ntf
        )

        assert sent is False
        assert REF not in billing.claims
        assert billing.release_calls == 1

    async def test_blocked_bot_keeps_the_claim(self):
        billing = FakeBilling()
        ntf = AsyncMock()
        ntf.notify_user.return_value = None

        sent = await offer_source_survey(
            user=_new_user(), billing=billing, notification_service=ntf
        )

        assert sent is False
        assert REF in billing.claims


class TestKeyboard:
    def test_seven_options_one_per_row_with_prefixed_callbacks(self):
        markup = get_source_survey_keyboard()
        rows = markup.inline_keyboard

        assert [len(row) for row in rows] == [1] * 7
        data = [row[0].callback_data for row in rows]
        assert data == [f"{SOURCE_SURVEY_PREFIX}{a.value}" for a in SourceSurveyAnswer]
        assert all(len(d.encode()) <= 64 for d in data)

    def test_answer_codes_fit_the_billing_pattern(self):
        import re

        for answer in SourceSurveyAnswer:
            assert re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}", answer.value)


class TestAnswerCallback:
    async def test_option_is_stored_and_thanked(self):
        billing = FakeBilling()
        billing.claims[REF] = None
        callback = _callback(f"{SOURCE_SURVEY_PREFIX}FRIEND")
        redis = _redis()
        ntf = AsyncMock()
        before = _sent("FRIEND")

        raw = unwrap_inject(on_source_survey_answer)
        await raw(callback, _new_user(), make_i18n(), billing, redis, ntf)

        assert billing.claims[REF] == "FRIEND"
        callback.message.edit_text.assert_awaited_once()
        assert callback.message.edit_text.await_args.kwargs["text"] == "[msg-source-survey-thanks]"
        assert callback.message.edit_text.await_args.kwargs["reply_markup"] is None
        assert _sent("FRIEND") == before + 1
        ntf.system_notify.assert_awaited_once()
        kwargs = ntf.system_notify.await_args.kwargs["payload"].i18n_kwargs
        assert kwargs["answer"] == "FRIEND"

    async def test_other_asks_for_one_short_reply_and_is_already_counted(self):
        billing = FakeBilling()
        billing.claims[REF] = None
        callback = _callback(f"{SOURCE_SURVEY_PREFIX}OTHER")
        redis = _redis()

        raw = unwrap_inject(on_source_survey_answer)
        await raw(callback, _new_user(), make_i18n(), billing, redis, AsyncMock())

        assert billing.claims[REF] == "OTHER"
        assert (
            callback.message.edit_text.await_args.kwargs["text"]
            == "[msg-source-survey-other-prompt]"
        )
        awaiting = [c for c in redis.set.await_args_list if "awaiting" in c.args[0]]
        assert len(awaiting) == 1
        assert awaiting[0].kwargs["ex"] == 30 * 60

    async def test_unknown_option_is_ignored(self):
        billing = FakeBilling()
        billing.claims[REF] = None
        callback = _callback(f"{SOURCE_SURVEY_PREFIX}NOPE")

        raw = unwrap_inject(on_source_survey_answer)
        await raw(callback, _new_user(), make_i18n(), billing, _redis(), AsyncMock())

        assert billing.claims[REF] is None
        callback.message.edit_text.assert_not_called()
        callback.answer.assert_awaited_once()

    async def test_second_tap_does_not_store_again(self):
        billing = FakeBilling()
        billing.claims[REF] = None
        redis = _redis()
        redis.set.return_value = None
        callback = _callback(f"{SOURCE_SURVEY_PREFIX}SEARCH")

        raw = unwrap_inject(on_source_survey_answer)
        await raw(callback, _new_user(), make_i18n(), billing, redis, AsyncMock())

        assert billing.claims[REF] is None
        callback.answer.assert_awaited_once_with(text="[msg-source-survey-already-answered]")

    async def test_answer_without_a_survey_claim_is_ignored(self):
        billing = FakeBilling()
        callback = _callback(f"{SOURCE_SURVEY_PREFIX}SEARCH")
        redis = _redis()
        ntf = AsyncMock()

        raw = unwrap_inject(on_source_survey_answer)
        await raw(callback, _new_user(), make_i18n(), billing, redis, ntf)

        assert billing.claims == {}
        callback.message.edit_text.assert_not_called()
        ntf.system_notify.assert_not_called()
        redis.delete.assert_awaited()

    async def test_billing_error_does_not_crash_the_handler(self):
        billing = AsyncMock()
        billing.answer_user_reminder.side_effect = RuntimeError("billing down")
        callback = _callback(f"{SOURCE_SURVEY_PREFIX}SITE")
        redis = _redis()

        raw = unwrap_inject(on_source_survey_answer)
        await raw(callback, _new_user(), make_i18n(), billing, redis, AsyncMock())

        callback.message.edit_text.assert_not_called()
        redis.delete.assert_awaited()


class TestOtherText:
    async def test_text_is_sanitized_stored_and_forwarded(self):
        billing = FakeBilling()
        billing.claims[REF] = "OTHER"
        message = _message("  друг\x00 из   чата\n\n​про vpn  ")
        redis = _redis()
        ntf = AsyncMock()

        raw = unwrap_inject(on_source_survey_other_text)
        await raw(message, _new_user(), make_i18n(), billing, ntf, redis)

        assert billing.answer_texts[REF] == "друг из чата про vpn"
        message.answer.assert_awaited_once_with(text="[msg-source-survey-thanks]")
        redis.delete.assert_awaited_once()
        kwargs = ntf.system_notify.await_args.kwargs["payload"].i18n_kwargs
        assert kwargs["answer"] == "OTHER"
        assert kwargs["text"] == "друг из чата про vpn"

    async def test_text_is_escaped_for_the_admin_card(self):
        billing = FakeBilling()
        billing.claims[REF] = "OTHER"
        message = _message("<b>x</b> & y")
        ntf = AsyncMock()

        raw = unwrap_inject(on_source_survey_other_text)
        await raw(message, _new_user(), make_i18n(), billing, ntf, _redis())

        assert billing.answer_texts[REF] == "<b>x</b> & y"
        kwargs = ntf.system_notify.await_args.kwargs["payload"].i18n_kwargs
        assert kwargs["text"] == "&lt;b&gt;x&lt;/b&gt; &amp; y"

    async def test_long_text_is_capped_at_200_characters(self):
        billing = FakeBilling()
        billing.claims[REF] = "OTHER"

        raw = unwrap_inject(on_source_survey_other_text)
        await raw(_message("я" * 500), _new_user(), make_i18n(), billing, AsyncMock(), _redis())

        assert len(billing.answer_texts[REF]) == 200

    async def test_text_that_sanitizes_to_nothing_stores_no_text(self):
        billing = FakeBilling()
        billing.claims[REF] = "OTHER"
        message = _message(" \x00​ \n ")

        raw = unwrap_inject(on_source_survey_other_text)
        await raw(message, _new_user(), make_i18n(), billing, AsyncMock(), _redis())

        assert REF not in billing.answer_texts
        message.answer.assert_awaited_once_with(text="[msg-source-survey-thanks]")

    async def test_billing_error_keeps_the_conversation_alive(self):
        billing = AsyncMock()
        billing.answer_user_reminder.side_effect = RuntimeError("billing down")
        message = _message("друг")

        raw = unwrap_inject(on_source_survey_other_text)
        await raw(message, _new_user(), make_i18n(), billing, AsyncMock(), _redis())

        message.answer.assert_not_called()


class TestAwaitingFilter:
    @staticmethod
    def _data(redis):
        container = MagicMock()
        container.get = AsyncMock(return_value=redis)
        return {"dishka_container": container}

    @staticmethod
    def _msg(text, user_id=TG):
        message = MagicMock()
        message.text = text
        message.from_user = MagicMock(id=user_id)
        return message

    async def test_matches_only_while_the_user_owes_a_reply(self):
        redis = _redis()
        redis.get.return_value = b"1"
        assert await AwaitingSourceSurveyText()(self._msg("друг"), **self._data(redis)) is True

        redis.get.return_value = None
        assert await AwaitingSourceSurveyText()(self._msg("друг"), **self._data(redis)) is False

    async def test_a_command_is_not_taken_as_the_answer(self):
        redis = _redis()
        redis.get.return_value = b"1"

        matched = await AwaitingSourceSurveyText()(self._msg("/start"), **self._data(redis))

        assert matched is False
        redis.delete.assert_awaited_once()


class TestSanitize:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("  привет  ", "привет"),
            ("a\tb\nc", "a b c"),
            ("a\x00b\x07c", "abc"),
            ("a​b", "ab"),
            ("", ""),
            ("я" * 300, "я" * 200),
        ],
    )
    def test_cases(self, raw, expected):
        assert sanitize_free_text(raw) == expected


class TestTranslations:
    @staticmethod
    def _translator():
        from fluentogram import TranslatorHub
        from fluentogram.storage import FileStorage

        hub = TranslatorHub(
            {"ru": ("ru",)},
            root_locale="ru",
            storage=FileStorage(path=Path("assets/translations") / "{locale}"),
        )
        return hub.get_translator_by_locale("ru")

    def test_every_option_has_a_button_label(self):
        i18n = self._translator()
        for row in get_source_survey_keyboard().inline_keyboard:
            label = i18n.get(row[0].text)
            assert label and label != row[0].text

    def test_prompt_and_replies_render(self):
        i18n = self._translator()
        assert "Как вы о нас узнали?" in i18n.get("ntf-source-survey-prompt")
        for key in (
            "msg-source-survey-thanks",
            "msg-source-survey-other-prompt",
            "msg-source-survey-already-answered",
        ):
            assert i18n.get(key) != key

    @pytest.mark.parametrize("answer", list(SourceSurveyAnswer))
    def test_admin_card_names_the_answer(self, answer):
        i18n = self._translator()
        card = i18n.get(
            "ntf-event-source-survey",
            user_id="1",
            user_name="Анна",
            username="anna",
            answer=answer.value,
            text="от подруги" if answer is SourceSurveyAnswer.OTHER else False,
        )
        assert "#EventSourceSurvey" in card
        assert "Источник (ответ)" in card
        assert ("от подруги" in card) is (answer is SourceSurveyAnswer.OTHER)
