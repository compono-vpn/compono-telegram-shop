#!/usr/bin/env python3
"""Mutation check for the shop's TV pairing: one bug at a time, run tests/test_tv_pair.py
(and the source/attribution tests), expect a failure, restore."""
import os
import subprocess
import sys

WT = os.environ.get("WT", ".")
MUTATIONS = [
    ("src/services/tv_pair.py", 'CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"',
     'CODE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"', "accept I/L/O/U"),
    ("src/services/tv_pair.py", "re.IGNORECASE)\n# /start", ")\n# /start", "payload case-sensitive"),
    ("src/services/tv_pair.py", 'return param.strip()[len(TV_PAIR_PREFIX) :].upper()',
     'return param.strip()[len(TV_PAIR_PREFIX) :]', "code not upper-cased"),
    ("src/services/tv_pair.py", 'return code if _CODE_RE.match(code) else None', 'return code or None',
     "callback code not validated"),
    ("src/services/tv_pair.py", 'return f"{code[:4]}-{code[4:]}"', "return code", "display without dash"),
    ("src/services/tv_pair.py", 'return f"{code[:2]}******" if len(code) > 2 else "**"', "return code",
     "full code logged"),
    ("src/bot/routers/extra/tv_pair.py", "    if result is TvPairClaim.ALREADY_CLAIMED:\n        await _edit(callback, i18n.get(\"msg-tv-pair-used\"))",
     "    if result is TvPairClaim.ALREADY_CLAIMED:\n        await _edit(callback, i18n.get(\"msg-tv-pair-attached\"))",
     "409 shown as success"),
    ("src/bot/routers/extra/tv_pair.py", "        await open_checkout(\n", "        pass\n        await (lambda *a, **k: __import__('asyncio').sleep(0))(\n",
     "422 does not open plans"),
    ("src/bot/routers/extra/tv_pair.py", "reply_markup=retry_keyboard(code, i18n.get(\"btn-tv-pair-retry\")),", "reply_markup=None,",
     "422 drops the retry button"),
    ("src/bot/routers/extra/tv_pair.py", "result = await api_client.claim_tv_pair(code, user.telegram_id)",
     "result = await api_client.claim_tv_pair(code, 1)", "claims for a fixed id"),
    ("src/infrastructure/api/client.py", "    422: TvPairClaim.NO_SUBSCRIPTION,\n", "", "422 not mapped"),
    ("src/infrastructure/api/client.py", '"/tv-pair/claim",', '"/tv-pair/claim/",', "wrong path"),
    ("src/infrastructure/api/client.py", 'json={"code": code, "telegramId": telegram_id},',
     'json={"code": code, "telegram_id": telegram_id},', "wrong body field"),
    ("src/infrastructure/api/client.py", "            if response.status_code in expected_errors:", "            if False:",
     "expected answers logged as errors"),
    ("src/bot/routers/menu/handlers.py", "@router.message(CommandStart(ignore_case=True), _is_tv_pair_start)",
     "@router.message(CommandStart(ignore_case=True), lambda m: False)", "start handler never matches (unit tests do not route; e2e does)"),
    ("assets/translations/ru/messages.ftl", "Нажмите, только если этот код сейчас на экране вашего телевизора.",
     "Нажмите.", "anti-phishing sentence dropped"),
]


def main() -> int:
    for rel, old, new, label in MUTATIONS:
        path = os.path.join(WT, rel)
        src = open(path, encoding="utf-8").read()
        if src.count(old) != 1:
            print(f"| {label} | NOT APPLIED (count {src.count(old)}) |")
            continue
        open(path, "w", encoding="utf-8").write(src.replace(old, new))
        try:
            p = subprocess.run(
                "uv run pytest -q -p no:cacheprovider tests/test_tv_pair.py tests/test_attribution.py tests/test_on_start_command.py",
                shell=True, cwd=WT, capture_output=True, text=True, timeout=600,
            )
            fails = sorted({ln.split("::")[1].split(" ")[0] for ln in p.stdout.splitlines()
                            if ln.startswith("FAILED") and "::" in ln})
            res = ("caught by " + ", ".join(fails[:3]) + (" ..." if len(fails) > 3 else "")) if p.returncode else "NOT CAUGHT"
        finally:
            open(path, "w", encoding="utf-8").write(src)
        print(f"| {label} | {res} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
