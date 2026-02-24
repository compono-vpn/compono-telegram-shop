import time
import traceback
from typing import Any

from aiogram.utils.formatting import Text
from loguru import logger
from taskiq import TaskiqMessage, TaskiqResult
from taskiq.abc.middleware import TaskiqMiddleware

from src.core.metrics import TASKIQ_TASK_DURATION, TASKIQ_TASK_ERRORS_TOTAL
from src.core.utils.message_payload import MessagePayload


class MetricsMiddleware(TaskiqMiddleware):
    _task_start_times: dict[str, float]

    def __init__(self) -> None:
        super().__init__()
        self._task_start_times = {}

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        self._task_start_times[message.task_id] = time.monotonic()
        return message

    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
    ) -> None:
        start = self._task_start_times.pop(message.task_id, None)
        if start is not None:
            duration = time.monotonic() - start
            TASKIQ_TASK_DURATION.labels(task_name=message.task_name).observe(duration)


class ErrorMiddleware(TaskiqMiddleware):
    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
        exception: BaseException,
    ) -> None:
        error_type_name = type(exception).__name__
        TASKIQ_TASK_ERRORS_TOTAL.labels(
            task_name=message.task_name, error_type=error_type_name
        ).inc()
        logger.error(f"Task '{message.task_name}' error: {exception}")
        from src.infrastructure.taskiq.tasks.notifications import (  # noqa: PLC0415
            send_error_notification_task,
        )

        traceback_str = "".join(
            traceback.format_exception(type(exception), exception, exception.__traceback__)
        )
        error_message = Text(str(exception)[:512])

        await send_error_notification_task.kiq(
            error_id=message.task_id,
            traceback_str=traceback_str,
            payload=MessagePayload.not_deleted(
                i18n_key="ntf-event-error",
                i18n_kwargs={
                    "user": False,
                    "error": f"{error_type_name}: {error_message.as_html()}",
                },
            ),
        )
