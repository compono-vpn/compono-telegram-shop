"""Tests for SupervisedKafkaConsumer: commit-after-success semantics and
crash supervision (restart with backoff, liveness metrics).

Covers the BDT-409 hazard: both Kafka consumers were at-most-once
(enable_auto_commit=True) and died silently on any unexpected exception,
leaving the consumer dead for the pod's whole lifetime with no signal.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY

from src.infrastructure.kafka.base_consumer import SupervisedKafkaConsumer


def _metric_value(name: str, consumer: str) -> float | None:
    return REGISTRY.get_sample_value(name, {"consumer": consumer})


class _FakeConsumer(SupervisedKafkaConsumer):
    def __init__(self, consumer_name: str, handle_message=None) -> None:
        config = MagicMock()
        config.kafka_brokers = "localhost:9092"
        super().__init__(config=config, container=MagicMock())
        self.consumer_name = consumer_name
        self._handle = handle_message or AsyncMock()
        # Fast backoff for tests.
        self._initial_backoff = 0.001
        self._max_backoff = 0.002
        self._backoff_multiplier = 2.0

    @property
    def topic(self) -> str:
        return "test.topic"

    @property
    def group_id(self) -> str:
        return "test-group"

    async def _handle_message(self, payload: dict) -> None:
        await self._handle(payload)


def _make_aiokafka_consumer_mock(messages: list, *, end_with_exception: Exception | None = None):
    """Build a mock AIOKafkaConsumer whose async iteration yields `messages`
    (each wrapped with a `.value` attribute) and then either stops or raises."""
    mock_consumer = MagicMock()
    mock_consumer.start = AsyncMock()
    mock_consumer.stop = AsyncMock()
    mock_consumer.commit = AsyncMock()

    async def _aiter():
        for value in messages:
            msg = MagicMock()
            msg.value = value
            yield msg
        if end_with_exception:
            raise end_with_exception

    mock_consumer.__aiter__ = lambda self: _aiter()
    return mock_consumer


class TestRunOnceCommitSemantics:
    async def test_commits_after_successful_handle(self):
        consumer = _FakeConsumer("test-commit-success")
        mock_kafka = _make_aiokafka_consumer_mock([{"foo": "bar"}])

        with patch(
            "src.infrastructure.kafka.base_consumer.AIOKafkaConsumer",
            return_value=mock_kafka,
        ):
            await consumer._run_once()

        consumer._handle.assert_awaited_once_with({"foo": "bar"})
        mock_kafka.commit.assert_awaited_once()

    async def test_does_not_commit_when_handler_raises(self):
        handler = AsyncMock(side_effect=ValueError("boom"))
        consumer = _FakeConsumer("test-commit-failure", handle_message=handler)
        mock_kafka = _make_aiokafka_consumer_mock([{"foo": "bar"}])

        with patch(
            "src.infrastructure.kafka.base_consumer.AIOKafkaConsumer",
            return_value=mock_kafka,
        ):
            with pytest.raises(ValueError, match="boom"):
                await consumer._run_once()

        mock_kafka.commit.assert_not_awaited()

    async def test_commits_each_message_independently(self):
        """Second message must not be committed if it fails, even though
        the first one succeeded (redelivery must be scoped to the failure)."""
        handler = AsyncMock(side_effect=[None, ValueError("boom")])
        consumer = _FakeConsumer("test-commit-partial", handle_message=handler)
        mock_kafka = _make_aiokafka_consumer_mock([{"n": 1}, {"n": 2}])

        with patch(
            "src.infrastructure.kafka.base_consumer.AIOKafkaConsumer",
            return_value=mock_kafka,
        ):
            with pytest.raises(ValueError):
                await consumer._run_once()

        assert mock_kafka.commit.await_count == 1


class TestSupervisorRestart:
    async def test_supervisor_restarts_after_consume_loop_crash(self):
        consumer_name = f"test-restart-{uuid4()}"
        consumer = _FakeConsumer(consumer_name)

        call_count = 0

        async def flaky_run_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("kafka connection dropped")
            consumer._stopping = True  # stop after the successful restart

        consumer._run_once = flaky_run_once  # type: ignore[method-assign]

        await consumer._supervise()

        assert call_count == 2
        assert _metric_value("kafka_consumer_restarts_total", consumer_name) == 1.0

    async def test_liveness_gauge_goes_down_on_crash(self):
        consumer_name = f"test-gauge-down-{uuid4()}"
        consumer = _FakeConsumer(consumer_name)

        async def crash_once():
            consumer._stopping = True
            raise RuntimeError("boom")

        consumer._run_once = crash_once  # type: ignore[method-assign]

        await consumer._supervise()

        assert _metric_value("kafka_consumer_up", consumer_name) == 0.0

    async def test_cancelled_error_does_not_count_as_restart(self):
        consumer_name = f"test-cancel-{uuid4()}"
        consumer = _FakeConsumer(consumer_name)

        async def cancelled():
            raise asyncio.CancelledError

        consumer._run_once = cancelled  # type: ignore[method-assign]

        with pytest.raises(asyncio.CancelledError):
            await consumer._supervise()

        assert _metric_value("kafka_consumer_restarts_total", consumer_name) is None


class TestStartStop:
    async def test_start_sets_up_supervisor_task(self):
        consumer_name = f"test-start-{uuid4()}"
        consumer = _FakeConsumer(consumer_name)
        consumer._supervise = AsyncMock()  # type: ignore[method-assign]

        await consumer.start()

        assert consumer._supervisor_task is not None
        await consumer.stop()

    async def test_start_skips_when_no_brokers_configured(self):
        consumer_name = f"test-nobrokers-{uuid4()}"
        consumer = _FakeConsumer(consumer_name)
        consumer._brokers = ""

        await consumer.start()

        assert consumer._supervisor_task is None

    async def test_stop_marks_consumer_down(self):
        consumer_name = f"test-stop-{uuid4()}"
        consumer = _FakeConsumer(consumer_name)
        consumer._supervise = AsyncMock()  # type: ignore[method-assign]

        await consumer.start()
        await consumer.stop()

        assert _metric_value("kafka_consumer_up", consumer_name) == 0.0
