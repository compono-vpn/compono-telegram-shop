from aiogram_dialog import DialogManager
from remnawave_api import RemnawaveSDK
from remnawave_api.models import (
    HostsResponseDto,
    InboundsResponseDto,
    NodesResponseDto,
    StatisticResponseDto,
)

from app.bot.middlewares.i18n import I18nFormatter
from app.core.constants import UNLIMITED
from app.core.formatters import (
    format_bytes,
    format_country_code,
    format_duration,
    format_percent,
)


async def system_getter(
    dialog_manager: DialogManager,
    remnawave: RemnawaveSDK,
    i18n_format: I18nFormatter,
    **kwargs,
) -> dict:
    stats: StatisticResponseDto = await remnawave.system.get_stats()

    return {  # NOTE: think about a models for translations
        "cpu_cores": stats.cpu.physical_cores,
        "cpu_threads": stats.cpu.cores,
        "ram_used": format_bytes(stats.memory.active, i18n_format),
        "ram_total": format_bytes(stats.memory.total, i18n_format),
        "ram_used_percent": format_percent(stats.memory.active, stats.memory.total),
        "uptime": format_duration(stats.uptime, i18n_format, True),
    }


async def users_getter(
    dialog_manager: DialogManager,
    remnawave: RemnawaveSDK,
    **kwargs,
) -> dict:
    stats: StatisticResponseDto = await remnawave.system.get_stats()

    return {
        "users_total": str(stats.users.total_users),
        "users_active": str(stats.users.status_counts.active),
        "users_disabled": str(stats.users.status_counts.disabled),
        "users_limited": str(stats.users.status_counts.limited),
        "users_expired": str(stats.users.status_counts.expired),
        "online_last_day": str(stats.online_stats.last_day),
        "online_last_week": str(stats.online_stats.last_week),
        "online_never": str(stats.online_stats.never_online),
        "online_now": str(stats.online_stats.online_now),
    }


async def hosts_getter(
    dialog_manager: DialogManager,
    remnawave: RemnawaveSDK,
    i18n_format: I18nFormatter,
    **kwargs,
) -> dict:
    hosts: HostsResponseDto = await remnawave.hosts.get_all_hosts()

    hosts_text = "\n".join(
        i18n_format(
            "msg-remnawave-host-details",
            {
                "remark": host.remark,
                "status": "off" if host.is_disabled else "on",
                "address": host.address,
                "port": str(host.port),
                "inbound_uuid": str(host.inbound_uuid),
            },
        )
        for host in hosts.response
    )

    return {"hosts": hosts_text}


async def nodes_getter(
    dialog_manager: DialogManager,
    remnawave: RemnawaveSDK,
    i18n_format: I18nFormatter,
    **kwargs,
) -> dict:
    nodes: NodesResponseDto = await remnawave.nodes.get_all_nodes()
    print(nodes.response[0].traffic_used_bytes)
    nodes_text = "\n".join(
        i18n_format(
            "msg-remnawave-node-details",
            {
                "country": format_country_code(node.country_code),
                "name": node.name,
                "status": "on" if node.is_connected else "off",
                "address": node.address,
                "port": str(node.port),
                "xray_uptime": format_duration(str(node.xray_uptime), i18n_format, True),
                "users_online": str(node.users_online),
                "traffic_used": format_bytes(
                    node.traffic_used_bytes, i18n_format
                ),  # FIXME: not for all time? (only 7 days period)
                "traffic_limit": (
                    format_bytes(node.traffic_limit_bytes, i18n_format, True)
                    if node.traffic_limit_bytes > 0
                    else UNLIMITED
                ),
            },
        )
        for node in nodes.response
    )

    return {"nodes": nodes_text}


async def inbounds_getter(
    dialog_manager: DialogManager,
    remnawave: RemnawaveSDK,
    i18n_format: I18nFormatter,
    **kwargs,
) -> dict:
    inbounds: InboundsResponseDto = await remnawave.inbounds.get_inbounds()

    inbounds_text = "\n".join(
        i18n_format(
            "msg-remnawave-inbound-details",
            {
                "uuid": str(inbound.uuid),
                "tag": inbound.tag,
                "type": inbound.type,
                "port": str(inbound.port),
                "network": inbound.network,
                "security": inbound.security,
            },
        )
        for inbound in inbounds.response
    )

    return {"inbounds": inbounds_text}
