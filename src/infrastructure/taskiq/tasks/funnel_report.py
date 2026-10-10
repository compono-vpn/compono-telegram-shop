import traceback
import uuid
from datetime import datetime
from typing import Optional

from aiogram.utils.formatting import Text
from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger

from src.core.config import AppConfig
from src.core.utils.message_payload import MessagePayload
from src.core.utils.time import MSK, compute_msk_previous_day_window
from src.infrastructure.api import ApiClient, ConnectedActivityStats
from src.infrastructure.billing import BillingClient
from src.infrastructure.taskiq.broker import broker
from src.services.notification import NotificationService


def _msk_label(moment: Optional[datetime]) -> str:
    if moment is None:
        return "never"
    return moment.astimezone(MSK).strftime("%Y-%m-%d %H:%M") + " MSK"


def _activity_lines(activity: Optional[ConnectedActivityStats]) -> str:
    """Connected-user count for the day with explicit coverage and freshness labels."""
    if activity is None:
        return "Connected users (observed on exit nodes): unavailable (activity endpoint failed)\n"

    if activity.fresh:
        freshness = f"node counters current ({activity.nodes_fresh}/{activity.nodes_total} nodes)"
    else:
        ok = (
            "never completed"
            if activity.oldest_apply_ok_at is None
            else f"oldest ok {_msk_label(activity.oldest_apply_ok_at)}"
        )
        freshness = f"STALE: only {activity.nodes_fresh}/{activity.nodes_total} nodes current, {ok}"

    if activity.covers_range:
        coverage = "covers the whole day"
    elif activity.since is None:
        coverage = "NO DATA: collector has not covered every exit node yet"
    else:
        coverage = f"PARTIAL: recording only started {_msk_label(activity.since)}"

    return (
        f"Connected users (observed on exit nodes): {activity.connected_users}\n"
        "  Direct and per-user routes only. Relay (whitelist) users are not observable "
        "and are not counted.\n"
        f"  Collector: {coverage}; {freshness}; "
        f"last recorded activity {_msk_label(activity.last_observation_at)}\n"
    )


async def _build_funnel_report_text(
    billing: BillingClient,
    api_client: ApiClient,
    now: Optional[datetime] = None,
) -> str:
    start_utc, end_utc = compute_msk_previous_day_window(now)

    funnel_stats = await billing.get_funnel_stats(start_utc, end_utc)
    connected_stats = await api_client.get_connected_stats(start_utc, end_utc)

    profile_stats = await api_client.get_profile_requester_stats(start_utc, end_utc)

    activity: Optional[ConnectedActivityStats]
    try:
        activity = await api_client.get_connected_activity(start_utc, end_utc)
    except Exception as exception:
        logger.warning(f"Connected activity unavailable for daily report: {exception}")
        activity = None

    report_date = start_utc.astimezone(MSK).date().isoformat()

    return (
        f"📊 Daily activity — {report_date}\n\n"
        f"New users: {funnel_stats.new_users}\n"
        f"Used trial: {funnel_stats.used_trial}\n"
        f"Profile requesters: {profile_stats.profile_requesters}\n"
        f"{_activity_lines(activity)}"
        f"Last seen on VPN that day: {connected_stats.connected}\n"
        f"Paid purchases: {funnel_stats.bought_sub}\n\n"
        "Daily totals, not a signup cohort. Profile requests include refreshes and failures. "
        "Last-seen counts can decrease after later activity."
    )


async def send_daily_funnel_report(
    config: AppConfig,
    billing: BillingClient,
    api_client: ApiClient,
    notification_service: NotificationService,
    now: Optional[datetime] = None,
) -> None:
    """Build and deliver the daily funnel report to the admin (dev) Telegram chat.

    On failure to reach either internal API, routes the failure through the
    standard error-notification pipeline instead of dropping it silently.
    """
    try:
        text = await _build_funnel_report_text(billing, api_client, now)
    except Exception as exception:
        logger.exception(f"Failed to build daily funnel report: {exception}")
        traceback_str = traceback.format_exc()
        error_type_name = type(exception).__name__
        error_message = Text(str(exception)[:512])

        await notification_service.error_notify(
            error_id=str(uuid.uuid4()),
            traceback_str=traceback_str,
            payload=MessagePayload.not_deleted(
                i18n_key="ntf-event-error",
                i18n_kwargs={
                    "user": False,
                    "error": f"{error_type_name}: {error_message.as_html()}",
                },
            ),
        )
        return

    await notification_service.bot.send_message(
        chat_id=config.bot.dev_id,
        text=text,
    )
    logger.info("Sent daily funnel report to admin")


@broker.task(schedule=[{"cron": "0 6 * * *"}], retry_on_error=False)
@inject
async def send_daily_funnel_report_task(
    config: FromDishka[AppConfig],
    billing: FromDishka[BillingClient],
    api_client: FromDishka[ApiClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    await send_daily_funnel_report(config, billing, api_client, notification_service)
