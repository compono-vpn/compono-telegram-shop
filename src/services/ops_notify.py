from typing import Any, Optional

import httpx
from loguru import logger

from src.core.config import AppConfig

_TIMEOUT = 10.0


async def post_ops_event(
    config: AppConfig,
    *,
    title: str,
    summary: str,
    details: dict[str, Any],
    key: Optional[str] = None,
    topic: str = "general",
) -> bool:
    url = config.notify_url.rstrip("/")
    token = config.notify_token.get_secret_value()
    if not url or not token:
        logger.warning(f"Ops notify is not configured, event '{title}' was not sent")
        return False

    body: dict[str, Any] = {
        "kind": "info",
        "severity": "info",
        "title": title,
        "summary": summary,
        "details": details,
        "topic": topic,
    }
    if key:
        body["key"] = key

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{url}/v1/event",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exception:
        logger.warning(f"Ops notify request failed for '{title}': {exception}")
        return False

    if response.status_code >= 300:
        logger.warning(
            f"Ops notify rejected '{title}': HTTP {response.status_code} {response.text[:200]}"
        )
        return False
    return True
