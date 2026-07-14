from __future__ import annotations

import ast
import re
from pathlib import Path

GETTERS_PATH = Path("src/bot/routers/menu/getters.py")
INVITE_KEY = "referral-invite-message"


def _invite_externals() -> set[str]:
    bundle = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("assets/translations/ru").glob("*.ftl")
    )
    match = re.search(
        rf"^{INVITE_KEY}\s*=(.*?)(?=^[A-Za-z0-9#]|\Z)",
        bundle,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"{INVITE_KEY} missing from ru bundle"
    return set(re.findall(r"\{\s*\$([A-Za-z_][A-Za-z0-9_]*)\s*\}", match.group(1)))


def _invite_render_kwargs() -> list[set[str]]:
    tree = ast.parse(GETTERS_PATH.read_text(encoding="utf-8"))
    calls: list[set[str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == INVITE_KEY
        ):
            calls.append({kw.arg for kw in node.keywords if kw.arg})
    return calls


def test_referral_invite_message_externals_supplied_at_every_render_site() -> None:
    externals = _invite_externals()
    render_calls = _invite_render_kwargs()

    assert render_calls, f"no i18n.get('{INVITE_KEY}', ...) call sites found in getters"
    for kwargs in render_calls:
        missing = externals - kwargs
        assert not missing, f"{INVITE_KEY} render missing externals {missing}; supplied {kwargs}"
