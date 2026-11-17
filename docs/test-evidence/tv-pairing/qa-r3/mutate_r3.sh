#!/bin/bash
# QA round 3 (shop): mutants for the dropped-connection e2e. Run from the repo root with
# SHOP_E2E_REDIS_SERVER and SHOP_E2E_API_BIN set. Restores every file afterwards.
set -u
OUT=docs/test-evidence/tv-pairing/qa-r3/mutation-r3-shop.txt
: > "$OUT"
run() {  # name file perl-expr pytest-k
  local bak
  bak=$(mktemp)
  cp "$2" "$bak"
  perl -0pi -e "$3" "$2"
  if cmp -s "$bak" "$2"; then echo "NOT-APPLIED $1" >> "$OUT"; rm -f "$bak"; return; fi
  if SHOP_E2E=1 uv run pytest tests/e2e/test_tv_pair_qa3_e2e.py tests/test_tv_pair.py -q -p no:cacheprovider -k "$4" >/dev/null 2>&1; then
    echo "SURVIVED $1" >> "$OUT"
  else
    echo "CAUGHT   $1" >> "$OUT"
  fi
  cp "$bak" "$2"
  rm -f "$bak"
}
run "a network error is reported as attached" src/infrastructure/api/client.py \
  's/_TV_PAIR_BY_STATUS.get\(e.status_code, TvPairClaim.FAILED\)/_TV_PAIR_BY_STATUS.get(e.status_code, TvPairClaim.ATTACHED)/' "lost or reset"
run "a network error escapes the client" src/infrastructure/api/client.py \
  's/except ApiClientError as e:\n            return _TV_PAIR_BY_STATUS/except KeyError as e:\n            return _TV_PAIR_BY_STATUS/' "lost or reset"
run "the failure alert edits the question instead" src/bot/routers/extra/tv_pair.py \
  's/    # Network error, 5xx, 401...: keep the buttons so the user can try again.\n/    # Network error, 5xx, 401...: keep the buttons so the user can try again.\n    await _edit(callback, i18n.get("msg-tv-pair-failed"))\n/' "lost or reset"
run "IGNORECASE without ASCII (round-3 bug back)" src/services/tv_pair.py \
  's/re.IGNORECASE \| re.ASCII/re.IGNORECASE/g' "lookalike or Lookalike"
cat "$OUT"
