"""Tests for the cancel-reason survey's raw (non-dialog) callback/message
router (BDT-442 foundation).

The survey uses a plain aiogram Router -- not aiogram-dialog -- so a user
mid-dialog (e.g. picking a plan) isn't disrupted when a cancel survey lands.
These tests unwrap dishka's @inject wrapper and call the handlers directly,
same approach used across the rest of this test suite (see
tests/test_on_start_command.py).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from aiogram.types import Message

from src.bot.routers.extra.cancel_survey import (
    AwaitingCancelSurveyText,
    on_cancel_survey_answer,
    on_cancel_survey_other_text,
)
from src.core.constants import CANCEL_SURVEY_PREFIX, CONTAINER_KEY
from src.core.enums import CancelSurveyReason
from src.core.metrics import CANCEL_SURVEY_ANSWERS_TOTAL
from src.core.storage.keys import CancelSurveyAnswerKey, CancelSurveyAwaitingTextKey
from tests.conftest import make_user, unwrap_inject


def _extract_events(experiment_service: AsyncMock) -> list[str]:
    events: list[str] = []
    for call in experiment_service.record_conversion.call_args_list:
        args, kwargs = call
        event = kwargs.get("event") if "event" in kwargs else (args[2] if len(args) > 2 else "")
        events.append(str(event))

    return events


def _extract_event_records(experiment_service: AsyncMock) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for call in experiment_service.record_conversion.call_args_list:
        args, kwargs = call
        key = (
            kwargs.get("experiment_key")
            if "experiment_key" in kwargs
            else (args[0] if args else "")
        )
        event = kwargs.get("event") if "event" in kwargs else (args[2] if len(args) > 2 else "")
        records.append((str(key), str(event)))

    return records


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


def _make_callback(data: str) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    return callback


class TestOnCancelSurveyAnswer:
    async def test_unknown_reason_is_ignored(self):
        user = make_user(telegram_id=1)
        callback = _make_callback(f"{CANCEL_SURVEY_PREFIX}{uuid4()}:NOT_A_REASON")
        redis_client = AsyncMock()
        redis_client.exists.return_value = 0
        billing = AsyncMock()
        experiment_service = MagicMock()
        i18n = MagicMock()
        i18n.get.side_effect = lambda key, **kwargs: f"[{key}]"

        raw = unwrap_inject(on_cancel_survey_answer)
        await raw(callback, user, i18n, billing, redis_client, experiment_service)

        callback.answer.assert_awaited_once_with()
        assert "rescue_clicked" in _extract_events(experiment_service)
        redis_client.hset.assert_not_awaited()

    async def test_malformed_payload_without_separator_is_ignored(self):
        user = make_user(telegram_id=1)
        callback = _make_callback(f"{CANCEL_SURVEY_PREFIX}not-a-uuid")
        redis_client = AsyncMock()
        redis_client.exists.return_value = 0
        billing = AsyncMock()
        experiment_service = MagicMock()
        i18n = MagicMock()
        i18n.get.side_effect = lambda key, **kwargs: f"[{key}]"

        raw = unwrap_inject(on_cancel_survey_answer)
        await raw(callback, user, i18n, billing, redis_client, experiment_service)

        callback.answer.assert_awaited_once_with()
        redis_client.hset.assert_not_awaited()

    async def test_invalid_payment_id_in_callback_is_ignored(self):
        user = make_user(telegram_id=1)
        callback = _make_callback(
            f"{CANCEL_SURVEY_PREFIX}not-a-uuid:{CancelSurveyReason.CARD_FAILED.value}"
        )
        redis_client = AsyncMock()
        redis_client.exists.return_value = 0
        billing = AsyncMock()
        experiment_service = MagicMock()
        i18n = MagicMock()
        i18n.get.side_effect = lambda key, **kwargs: f"[{key}]"

        raw = unwrap_inject(on_cancel_survey_answer)
        await raw(callback, user, i18n, billing, redis_client, experiment_service)

        callback.answer.assert_awaited_once_with()
        redis_client.hset.assert_not_awaited()
        billing.get_transaction.assert_not_awaited()

    async def test_experiment_events_use_payment_rescue_key(self, monkeypatch):
        monkeypatch.setattr(
            "src.bot.routers.extra.cancel_survey._SURVEY_EXPERIMENT_KEY",
            "payment_rescue",
        )

        payment_id = uuid4()
        user = make_user(telegram_id=42)
        callback = _make_callback(
            f"{CANCEL_SURVEY_PREFIX}{payment_id}:{CancelSurveyReason.CARD_FAILED.value}"
        )
        redis_client = AsyncMock()
        redis_client.exists.return_value = 0
        billing = AsyncMock()
        billing.get_transaction.return_value = MagicMock(GatewayType="YOOKASSA")
        experiment_service = MagicMock()
        i18n = MagicMock()
        i18n.get.side_effect = lambda key, **kwargs: f"[{key}]"

        raw = unwrap_inject(on_cancel_survey_answer)
        await raw(callback, user, i18n, billing, redis_client, experiment_service)

        records = _extract_event_records(experiment_service)
        assert ("payment_rescue", "rescue_clicked") in records
        assert ("payment_rescue", "cancel_reason_selected") in records

    async def test_already_answered_shows_toast_and_stops(self):
        payment_id = uuid4()
        user = make_user(telegram_id=1)
        callback = _make_callback(
            f"{CANCEL_SURVEY_PREFIX}{payment_id}:{CancelSurveyReason.TOO_EXPENSIVE.value}"
        )
        redis_client = AsyncMock()
        redis_client.exists.return_value = 1
        billing = AsyncMock()
        experiment_service = MagicMock()
        i18n = MagicMock()
        i18n.get.side_effect = lambda key, **kwargs: f"[{key}]"

        raw = unwrap_inject(on_cancel_survey_answer)
        await raw(callback, user, i18n, billing, redis_client, experiment_service)

        callback.answer.assert_awaited_once_with(text="[msg-cancel-survey-already-answered]")
        assert "rescue_clicked" in _extract_events(experiment_service)
        billing.get_transaction.assert_not_awaited()
        redis_client.hset.assert_not_awaited()

    async def test_other_reason_prompts_for_free_text(self):
        payment_id = uuid4()
        user = make_user(telegram_id=42)
        callback = _make_callback(
            f"{CANCEL_SURVEY_PREFIX}{payment_id}:{CancelSurveyReason.OTHER.value}"
        )
        redis_client = AsyncMock()
        redis_client.exists.return_value = 0
        billing = AsyncMock()
        experiment_service = MagicMock()
        i18n = MagicMock()
        i18n.get.side_effect = lambda key, **kwargs: f"[{key}]"

        raw = unwrap_inject(on_cancel_survey_answer)
        await raw(callback, user, i18n, billing, redis_client, experiment_service)

        awaiting_key = CancelSurveyAwaitingTextKey(telegram_id=42)
        redis_client.set.assert_awaited_once_with(awaiting_key.pack(), str(payment_id), ex=1800)
        assert "rescue_clicked" in _extract_events(experiment_service)
        callback.message.edit_text.assert_awaited_once()
        assert callback.message.edit_text.await_args.kwargs["reply_markup"] is None
        callback.answer.assert_awaited_once_with()
        billing.get_transaction.assert_not_awaited()

    async def test_direct_reason_records_answer_and_metric(self):
        payment_id = uuid4()
        user = make_user(telegram_id=42)
        callback = _make_callback(
            f"{CANCEL_SURVEY_PREFIX}{payment_id}:{CancelSurveyReason.CARD_FAILED.value}"
        )
        redis_client = AsyncMock()
        redis_client.exists.return_value = 0
        billing = AsyncMock()
        billing.get_transaction.return_value = MagicMock(GatewayType="YOOKASSA")
        experiment_service = MagicMock()
        i18n = MagicMock()
        i18n.get.side_effect = lambda key, **kwargs: f"[{key}]"

        before = _counter_value(
            CANCEL_SURVEY_ANSWERS_TOTAL, reason="CARD_FAILED", gateway="YOOKASSA"
        )

        raw = unwrap_inject(on_cancel_survey_answer)
        await raw(callback, user, i18n, billing, redis_client, experiment_service)

        answer_key = CancelSurveyAnswerKey(payment_id=payment_id)
        redis_client.hset.assert_awaited_once()
        hset_args = redis_client.hset.call_args
        assert hset_args[0][0] == answer_key.pack()
        mapping = hset_args[1]["mapping"]
        assert mapping["reason"] == "CARD_FAILED"
        assert mapping["gateway"] == "YOOKASSA"
        assert mapping["telegram_id"] == 42

        redis_client.expire.assert_awaited_once_with(answer_key.pack(), 90 * 24 * 60 * 60)

        after = _counter_value(
            CANCEL_SURVEY_ANSWERS_TOTAL, reason="CARD_FAILED", gateway="YOOKASSA"
        )
        assert after == before + 1
        assert "rescue_clicked" in _extract_events(experiment_service)
        assert "cancel_reason_selected" in _extract_events(experiment_service)

        callback.message.edit_text.assert_awaited_once()
        assert callback.message.edit_text.await_args.kwargs["text"] == "[msg-cancel-survey-thanks]"
        callback.answer.assert_awaited_once_with()


class TestOnCancelSurveyOtherText:
    def _make_message(self, text: str, telegram_id: int = 42) -> MagicMock:
        message = MagicMock()
        message.text = text
        message.caption = None
        message.answer = AsyncMock()
        return message

    async def test_records_free_text_and_forwards_to_dev(self):
        payment_id = uuid4()
        user = make_user(telegram_id=42)
        message = self._make_message("Карта не сработала, банк заблокировал")
        redis_client = AsyncMock()
        redis_client.exists.return_value = 0
        billing = AsyncMock()
        billing.get_transaction.return_value = MagicMock(GatewayType="CRYPTOMUS")
        notification_service = AsyncMock()
        experiment_service = MagicMock()
        i18n = MagicMock()
        i18n.get.side_effect = lambda key, **kwargs: f"[{key}]"

        raw = unwrap_inject(on_cancel_survey_other_text)
        await raw(
            message,
            user,
            str(payment_id),
            i18n,
            billing,
            notification_service,
            redis_client,
            experiment_service,
        )

        answer_key = CancelSurveyAnswerKey(payment_id=payment_id)
        redis_client.hset.assert_awaited_once()
        mapping = redis_client.hset.call_args[1]["mapping"]
        assert mapping["reason"] == "OTHER"
        assert mapping["other_text"] == "Карта не сработала, банк заблокировал"
        assert mapping["gateway"] == "CRYPTOMUS"
        redis_client.expire.assert_awaited_once_with(answer_key.pack(), 90 * 24 * 60 * 60)

        awaiting_key = CancelSurveyAwaitingTextKey(telegram_id=42)
        redis_client.delete.assert_awaited_once_with(awaiting_key.pack())

        notification_service.notify_super_dev.assert_awaited_once()
        payload = notification_service.notify_super_dev.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-event-cancel-survey-other"
        assert payload.i18n_kwargs["text"] == "Карта не сработала, банк заблокировал"
        assert "cancel_reason_selected" in _extract_events(experiment_service)

        message.answer.assert_awaited_once_with(text="[msg-cancel-survey-thanks]")

    async def test_invalid_payment_id_in_free_text_is_ignored(self):
        user = make_user(telegram_id=42)
        message = self._make_message("Как-то пошло не так")
        redis_client = AsyncMock()
        redis_client.exists.return_value = 0
        billing = AsyncMock()
        notification_service = AsyncMock()
        experiment_service = MagicMock()
        i18n = MagicMock()

        raw = unwrap_inject(on_cancel_survey_other_text)
        await raw(
            message,
            user,
            "not-a-uuid",
            i18n,
            billing,
            notification_service,
            redis_client,
            experiment_service,
        )

        redis_client.delete.assert_awaited_once_with(CancelSurveyAwaitingTextKey(telegram_id=42).pack())
        redis_client.hset.assert_not_awaited()
        notification_service.notify_super_dev.assert_not_awaited()

    async def test_empty_text_is_ignored(self):
        payment_id = uuid4()
        user = make_user(telegram_id=42)
        message = self._make_message("   ")
        redis_client = AsyncMock()
        redis_client.exists.return_value = 0
        billing = AsyncMock()
        notification_service = AsyncMock()
        experiment_service = MagicMock()
        i18n = MagicMock()

        raw = unwrap_inject(on_cancel_survey_other_text)
        await raw(
            message,
            user,
            str(payment_id),
            i18n,
            billing,
            notification_service,
            redis_client,
            experiment_service,
        )

        redis_client.hset.assert_not_awaited()
        notification_service.notify_super_dev.assert_not_awaited()

    async def test_already_answered_clears_awaiting_key_and_stops(self):
        payment_id = uuid4()
        user = make_user(telegram_id=42)
        message = self._make_message("some late reply")
        redis_client = AsyncMock()
        redis_client.exists.return_value = 1
        billing = AsyncMock()
        notification_service = AsyncMock()
        experiment_service = AsyncMock()
        i18n = MagicMock()

        raw = unwrap_inject(on_cancel_survey_other_text)
        await raw(
            message,
            user,
            str(payment_id),
            i18n,
            billing,
            notification_service,
            redis_client,
            experiment_service,
        )

        awaiting_key = CancelSurveyAwaitingTextKey(telegram_id=42)
        redis_client.delete.assert_awaited_once_with(awaiting_key.pack())
        notification_service.notify_super_dev.assert_not_awaited()
        message.answer.assert_not_awaited()


class TestAwaitingCancelSurveyTextFilter:
    async def test_returns_false_without_from_user(self):
        message = MagicMock()
        message.from_user = None

        result = await AwaitingCancelSurveyText()(message)

        assert result is False

    async def test_returns_false_when_no_pending_payment(self):
        message = MagicMock()
        message.from_user.id = 42
        redis_client = AsyncMock()
        redis_client.get.return_value = None
        container = AsyncMock()
        container.get.return_value = redis_client

        result = await AwaitingCancelSurveyText()(message, **{CONTAINER_KEY: container})

        assert result is False

    async def test_returns_payment_id_when_pending(self):
        payment_id = str(uuid4())
        message = MagicMock()
        message.from_user.id = 42
        redis_client = AsyncMock()
        redis_client.get.return_value = payment_id.encode()
        container = AsyncMock()
        container.get.return_value = redis_client

        result = await AwaitingCancelSurveyText()(message, **{CONTAINER_KEY: container})

        assert result == {"cancel_survey_payment_id": payment_id}
