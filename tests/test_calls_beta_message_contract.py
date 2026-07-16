"""Contract test: msg-calls-beta must not interpolate externals the render site doesn't supply.

Mirrors tests/test_referral_invite_message_contract.py but tracks msg-calls-beta,
which is rendered through MessagePayload(i18n_key=..., i18n_kwargs={...}) inside
src/bot/routers/menu/handlers.py rather than a direct i18n.get(...) call.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

HANDLERS_PATH = Path("src/bot/routers/menu/handlers.py")
CALLS_KEY = "msg-calls-beta"


def _calls_externals() -> set[str]:
    bundle = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("assets/translations/ru").glob("*.ftl")
    )
    match = re.search(
        rf"^{CALLS_KEY}\s*=(.*?)(?=^[A-Za-z0-9#]|\Z)",
        bundle,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"{CALLS_KEY} missing from ru bundle"
    return set(re.findall(r"\{\s*\$([A-Za-z_][A-Za-z0-9_]*)\s*\}", match.group(1)))


def _dict_literal_keys(node: ast.expr) -> set[str]:
    if not isinstance(node, ast.Dict):
        return set()
    return {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _calls_render_kwargs() -> list[set[str]]:
    tree = ast.parse(HANDLERS_PATH.read_text(encoding="utf-8"))
    calls: list[set[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            (isinstance(node.func, ast.Name) and node.func.id == "MessagePayload")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "not_deleted")
        ):
            continue

        i18n_key_value = None
        kwargs_keys: set[str] = set()
        for kw in node.keywords:
            if kw.arg == "i18n_key" and isinstance(kw.value, ast.Constant):
                i18n_key_value = kw.value.value
            if kw.arg == "i18n_kwargs":
                kwargs_keys = _dict_literal_keys(kw.value)

        if i18n_key_value == CALLS_KEY:
            calls.append(kwargs_keys)
    return calls


def test_calls_beta_message_externals_supplied_at_every_render_site() -> None:
    externals = _calls_externals()
    render_calls = _calls_render_kwargs()

    assert render_calls, f"no MessagePayload(i18n_key='{CALLS_KEY}', ...) call sites found in handlers"
    for kwargs in render_calls:
        missing = externals - kwargs
        assert not missing, f"{CALLS_KEY} render missing externals {missing}; supplied {kwargs}"
