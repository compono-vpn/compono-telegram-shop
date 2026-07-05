from __future__ import annotations

import re
from pathlib import Path

REQUIRED_SYSTEM_NOTIFICATION_KEYS = {
    "ntf-event-web-new-user",
    "ntf-event-web-subscription-new",
    "ntf-event-web-subscription-trial",
    "hdr-web-user",
    "frg-web-user",
}


def test_web_system_notification_keys_exist_in_ru_bundle() -> None:
    bundle = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("assets/translations/ru").glob("*.ftl")
    )
    keys = set(re.findall(r"^([a-z0-9][a-z0-9-]*)\s*=", bundle, flags=re.MULTILINE))

    missing = REQUIRED_SYSTEM_NOTIFICATION_KEYS - keys

    assert not missing
