# Testing: TV pairing in the bot (COM-202)

Run on 2026-11-17 on `feat/tv-pairing`, macOS arm64, Python 3.12 (`uv sync`), Redis 7.4.1 built
from source for the e2e. Evidence: `docs/test-evidence/tv-pairing/`.

## Gates

| Gate | Command | Result |
|---|---|---|
| lint | `uv run ruff check src/` | All checks passed |
| format | `uv run ruff format --check src/` | 202 files already formatted |
| unit tests, whole repo | `uv run pytest tests/` | 1378 passed, 2 skipped (the two opt-in e2e modules), 0 failed (the 1280 existing tests also passed with the new code before the new tests were added) |
| new unit tests | `uv run pytest tests/test_tv_pair.py` | 98 passed |
| e2e, in-memory claim | `SHOP_E2E=1 SHOP_E2E_REDIS_SERVER=… uv run pytest tests/e2e` | 14 passed (6 existing + 8 new) |
| e2e, real compono-api | `SHOP_E2E=1 SHOP_E2E_API_BIN=<compono-api feat/tv-pairing 90610ba build> … pytest tests/e2e/test_tv_pair_e2e.py` | 8 passed |

In the real-API e2e the test is the TV: it creates the pairing with `POST /api/v1/tv/pair` on a
locally running compono-api, the real bot (tgmock) gets `/start tv-<code>`, the test taps the
button, the bot's claim is forwarded to that API, and the test polls `/api/v1/tv/pair/poll` until
it receives the subscription URL (the fake billing's URL for that user), and then 410 on replay.

## Test matrix

| Case | How | Result | Where |
|---|---|---|---|
| `/start tv-<CODE>` asks first, shows `K7M4-QX9P`, buttons `tvp:<CODE>` and `tvx`, no claim on /start | unit + e2e (both modes) | pass | `TestStartHandler`; e2e `open_link` asserts no claim request was made |
| Payload parsing: lower/upper case, `/start@bot`, extra spaces; rejects 7/9 chars, dash, I/L/O/U, `tv_`, Cyrillic, extra words | unit | pass | `TestStartPayload`, `TestStartText` |
| No collision with `source-`, `ref_`, `aff-`, `web_`, `proxy`, `beta_testers`, `rs_`, `purchase_`, `gt_`, `enc_` | unit | pass | `test_other_payloads_are_not_tv`, `test_prefix_collides_with_no_existing_payload` |
| Attribution unchanged: `tv-` decodes to None (source None, admin card "Прямой заход"); `source-` legacy and v1 still decode; a new user from a TV link is created with source/attribution None; a new user from `source-a1_site-header_lios_ry` still gets source `site-header` and the attribution touch | unit + e2e | pass | `TestAttributionIsUntouched`; e2e `test_new_user_via_tv_link_has_no_source`, `test_source_link_still_attributes`; existing `tests/test_attribution.py` still passes |
| Paid user taps «Подключить» → claim `{"code","telegramId"}` for the tapping user → «Готово…», buttons removed → TV receives the URL once, 410 after | unit + e2e (real API) | pass | `TestConfirmHandler.test_attached`; e2e `test_paid_user_pairs_tv` |
| No subscription → «нужна активная подписка» with a retry button as a NEW message (see QA round 1), plan list opened; the code stays pending; after buying, the retry attaches | unit + e2e (real API) | pass | `test_no_subscription_opens_plans_and_keeps_a_retry`; e2e `test_user_without_subscription_gets_plans_then_retries` |
| Code already claimed by someone else → «Этот код уже использован» | unit + e2e | pass | `test_final_answers_remove_the_buttons`; e2e `test_code_used_by_someone_else` |
| Unknown or expired code → «Код устарел» | unit + e2e | pass | same; e2e `test_expired_or_unknown_code` |
| 429 and failures (network, 400, 401, 5xx, non-JSON body) → alert, question and buttons kept | unit | pass | `test_transient_answers_keep_the_question`, `TestClaimClient` |
| Malformed or forged button data never reaches the API | unit | pass | `test_malformed_button_never_calls_the_api`, `TestCallbackData` |
| Cancel → «Отменено», no claim, TV still pending | unit + e2e | pass | `TestCancelHandler`; e2e `test_cancel_does_not_claim` |
| Plain `/start` still opens the main menu | e2e | pass | `test_plain_start_still_opens_main_menu`; existing e2e |
| API client: exact path, header, body; every status mapped; network error → FAILED without raising | unit (httpx MockTransport) | pass | `TestClaimClient` |
| Logs: the code never appears; 404 is logged at INFO, 503 at ERROR; shop log of the e2e has no full code | unit + e2e | pass | `test_logs_never_carry_the_code_and_expected_answers_are_not_errors`; e2e asserts `code not in shop.log()` |
| Russian copy rendered with the real fluent files: contract sentences present, no price in the bot's new texts, alert texts within 200 chars | unit | pass | `TestCopy` |
| Review fix: a repeated tap with the same outcome (second «Подключить» while still without a subscription, or a double tap) makes Telegram refuse the edit with "message is not modified". Before the fix this escaped the handler: the tap was not answered, the error middleware sent `#EventError` and queued a main-menu redirect. Now that one refusal is ignored; any other `TelegramBadRequest` still raises | unit + e2e (both modes, refusal injected in tgmock because tgmock does not emulate it) | pass; the e2e failed ("the tap was not answered") with the old handler and passes with the fix | `TestUnchangedEdit`; e2e `test_second_tap_without_subscription_is_quiet` |
| Mutation check: 16 deliberate bugs | `mutate_shop.py` | 15 caught by unit tests; the 16th (start filter never matches) is not visible to unit tests and was caught by the e2e (1 failed) | `mutation-results.md` |

Two fixes to the e2e fake billing were needed to model real billing: `GET /users/{id}` for an
unknown user now answers 200 `null` (billing's `InternalHandler.GetUser`), and `POST /users`
creates the user. Without them no new-user flow could run in the e2e.

## Not tested, and why

- **Real Telegram and stage bot.** Not deployed; stage verification with `@compono_dev_bot` and the
  stage compono-api is still needed (and compono-api stage needs `TV_PAIR_BOT_USERNAME=compono_dev_bot`).
- **Real billing.** The e2e billing is a fake seeded with stage plans; compono-api read
  subscriptions from it.
- **Telegram clients' rendering** of the confirmation (HTML `<code>`) on phones: unverified.
- **Concurrency through the bot.** Concurrent claims are covered on the API side; here only
  sequential taps were driven.

## Review re-run (2026-11-17, independent reviewer)

Re-run on the review commit in a fresh worktree: `ruff check src/` all passed, `ruff format --check src/`
202 files formatted, `pytest tests/` 1382 passed, 2 skipped, 0 failed; e2e with the in-memory claim 15
passed; TV e2e against a compono-api binary built from `feat/tv-pairing` 90610ba: 9 passed.

## QA round 1 (2026-11-17, independent QA, branch `feat/tv-pairing`)

Fresh worktree, own Redis 7.4.1 (built from source), tgmock 0.2.0, and a compono-api binary built
from `feat/tv-pairing` including the QA round 1 API fixes. Evidence: `docs/test-evidence/tv-pairing/qa-r1/`.

### Bug found and fixed

**The «нужна активная подписка» message and its retry button were deleted the moment they appeared.**
The handler edited the tapped question into the explanation with a retry button, then opened the plan
list with `open_checkout` (`ShowMode.DELETE_AND_SEND`). aiogram-dialog treats the message a callback
came from as the dialog's old message and deletes it, so the user saw only a plan list, never the
explanation, and had no button to tap after buying (the author's e2e only checked that the edit was
sent, not that the message survived; tgmock records the `deleteMessage`). `ShowMode.SEND` would not
help: aiogram-dialog then strips that message's keyboard. Fix (`src/bot/routers/extra/tv_pair.py`):
the explanation and retry button are sent as a new message (`callback.message.answer`, or
`bot.send_message` to the user when the message is inaccessible), then the plan list opens and
replaces the tapped message. A retry tap that still has no subscription does the same, so exactly one
retry message stays visible. `open_checkout` and every other caller are unchanged.

Regression tests: `test_no_subscription_opens_plans_and_keeps_a_retry` (rewritten),
`test_no_subscription_message_is_sent_before_the_plan_list`,
`test_no_subscription_on_an_inaccessible_message_still_sends` (3 failed on the old handler:
`unit-before-fix.txt`), e2e `test_no_subscription_keeps_the_retry_message` (failed on the old handler
with `deleted message ids after the tap: {3}; question=3`: `e2e-before-fix.txt`), and the two author
e2e cases now assert the retry message is never deleted. The "message is not modified" guard from the
review stays for the attached/expired/used/cancel edits.

### Gates after the fix

| Gate | Result |
|---|---|
| `uv run ruff check src/` | All checks passed |
| `uv run ruff format --check src/` | 202 files already formatted |
| `uv run pytest tests/` | 1383 passed, 3 skipped (the three opt-in e2e modules), 0 failed |
| `SHOP_E2E=1 SHOP_E2E_API_BIN=<compono-api feat/tv-pairing + QA fixes> pytest tests/e2e` (whole e2e directory) | 35 passed, 0 failed (`e2e-after-fix-real-api.txt`) |

### QA e2e matrix (`tests/e2e/test_tv_pair_qa_e2e.py`, real bot + real compono-api)

| Case | Result |
|---|---|
| No subscription: the message with the explanation and the retry button exists and is never deleted | fail before fix, pass after |
| `/start TV-<code in lower case>` → question shows the upper-case code, claim sent with it | pass |
| Bad payloads `tv-ILOU1234`, `tv-ABC`, `tv-ABCDEFGH9`, `tv-`, `tv_ABCDEFGH`, `tv-ABCD-EFGH`, `xtv-ABCDEFGH` → normal main menu, no question, no claim | pass (7 cases) |
| Forged buttons `tvp:`, `tvp:ABC`, `tvp:ILOU1234`, `tvp:abcdefgh`, `tvp:ABCDEFGH1`, `tvp:../../x` → answered, no claim, no `#EventError` | pass (6 cases) |
| compono-api unreachable (claim forwarded to a closed port) → alert «Не получилось подключить телевизор…», no edit, buttons kept | pass |
| Guessing: 5 unknown codes → «Код устарел» ×5, the 6th tap (a real code) → alert «Слишком много попыток» | pass |
| Two «Подключить» taps delivered at the same moment → no `#EventError`, the TV pairs | pass |
| Secrets in logs after a full pairing: the full code, pollToken and subscription URL (and its token part) appear in neither the bot log nor the compono-api log | pass |
| Plain `/start` after a TV question → main menu | pass |

### Not tested in this round, and why

- Real Telegram clients and the stage bot: nothing is deployed (unverified).
- What the user sees in a real Telegram client for the new message order (explanation, then the plan
  list below it): observed only as tgmock calls (unverified on a phone).
- A real payment between the 422 and the retry: the e2e flips the fake billing's subscription instead.

## QA round 2 (2026-11-18, separate QA worktree, commit d16f427, no change to `src/`)

Round 2 found no new bug in the bot. It adds one e2e module, `tests/e2e/test_tv_pair_qa2_e2e.py`
(skipped unless `SHOP_E2E=1`, like the other e2e modules), and evidence under
`docs/test-evidence/tv-pairing/qa-r2/`.

### Gates

| Gate | Result |
|---|---|
| `uv run ruff check src/` / `ruff format --check src/` | pass / 202 files formatted |
| `uv run pytest tests/` | 1383 passed, 4 skipped (the four opt-in e2e modules), 0 failed |
| Whole `tests/e2e` against the real compono-api binary (dacf3c4), Redis 7.4.1 | 41 passed, 0 failed (`qa-r2/e2e-all-real-api.txt`; 35 before this round) |
| New module `ruff check` (T201 `print` ignored, as in the other e2e modules) and `ruff format` | pass |

### New e2e cases (real bot + tgmock + real compono-api)

| Case | Result |
|---|---|
| User sits in the promocode text input (a dialog `MessageInput`) and opens the TV link: the TV question appears, the `/start tv-` text is not sent to billing as a promocode, «Подключить» pairs the TV | pass |
| Three taps without a subscription: one new explanation each, no `#EventError`, the code stays pending; taps 4-11: the 11th claim gets the alert «Слишком много попыток…» (claim limit 10 per 10 min), no `#EventError` | pass |
| New user opens the TV link and taps «Отмена»: «Отменено», then a plain `/start` opens the main menu; the TV's code stays pending | pass |
| After buying and pairing through the newest retry message, a tap on an older copy of the retry message: «Код устарел», no `#EventError` | pass |
| One paid user pairs two TVs one after the other: both TVs get the same subscription URL | pass |
| The bot log holds none of the full codes used in the module | pass |

Red proof: with the `/start tv-` filter broken (`_is_tv_pair_start` always false) 5 of the 6 new cases
fail (`qa-r2/qa2-e2e-red-proof.txt`); the log-scan case passes either way. Source restored from git.

### Checked by reading or read-only, no test needed

- Router order: `menu.handlers` (with the `/start tv-` handler) is registered before every dialog
  router, so no dialog text input can swallow the link; the global `PrivateFilter` keeps the handler
  out of group chats.
- Production `platform.settings` (read-only SELECT): `rules_required=false`, `channel_required=false`,
  `access_mode=PUBLIC`. If either requirement is switched on, `RulesMiddleware`/`ChannelMiddleware`
  stop the `/start tv-` message and the payload is lost after the user accepts (same for every deep
  link today, not new).
- The bot's compono-api timeout is 30 s, longer than compono-api's 15 s billing timeout, so a slow
  billing gives the user the «Не получилось…» alert, never a hang. Telegram may then refuse the late
  `answerCallbackQuery` ("query is too old"), which the existing stale-callback handling counts and
  ignores.

### Observation, not changed (owner decision)

- A paid user whose subscription is LIMITED or EXPIRED gets 422 and the plan list opens with purchase
  type NEW (`open_checkout(..., PurchaseType.NEW)`), while the bot's own «Подписка» screen offers such a
  user «Продлить»/«Изменить» (RENEW/CHANGE). Billing accepts NEW and, since v0.47.9, extends the
  existing panel user, so nothing breaks, but the payment is recorded and announced as a new
  subscription, and the `intro_price` experiment (off in prod) would count it as a first purchase.

### Not tested in round 2, and why

- Real Telegram clients and the stage bot `@compono_dev_bot`: nothing is deployed (unverified).
- A real payment between the 422 and the retry: the e2e still flips the fake subscription.
- Rules/channel requirement switched on: off in prod, not exercised.
