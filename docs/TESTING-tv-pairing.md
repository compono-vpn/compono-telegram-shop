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
| Attribution (changed 2026-11-18, see the end of this file): `tv-` used to decode to None (source None, admin card "Прямой заход"); `source-` legacy and v1 still decode; a new user from a TV link is created with source/attribution None; a new user from `source-a1_site-header_lios_ry` still gets source `site-header` and the attribution touch | unit + e2e | pass | `TestAttributionIsUntouched`; e2e `test_new_user_via_tv_link_has_no_source`, `test_source_link_still_attributes`; existing `tests/test_attribution.py` still passes |
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

## QA round 3 (2026-11-18, separate QA worktree from 62991d0)

One bug found and fixed in `src/services/tv_pair.py`.

### Bug: typed look-alike letters were taken as a TV code

`re.IGNORECASE` in Python also folds a few non-ASCII letters onto ASCII ones (KELVIN SIGN U+212A
onto K, LATIN SMALL LETTER LONG S U+017F onto S). A typed `/start tv-` with the Kelvin sign got the
«Подключить телевизор?» question with a code that looks right, but the button carried a code the
callback parser refuses, so the tap did nothing. With the long s the bot asked about a different
code (`…S`). Telegram deep links cannot carry these letters, so only a hand-typed command hits it.
Fix: `re.ASCII` on both start regexes; such a command is now an ordinary /start.

Regression tests: `TestNonAsciiLookalikes` in `tests/test_tv_pair.py` (3 failed before the fix,
`qa-r3/lookalike-unit-before-fix.txt`) and `test_typed_lookalike_code_is_an_ordinary_start` in
`tests/e2e/test_tv_pair_qa3_e2e.py` (2 failed before the fix, `qa-r3/qa3-red-proof.txt`).

### New e2e cases (`tests/e2e/test_tv_pair_qa3_e2e.py`, real bot + tgmock + real compono-api with the round-3 API fix)

| Case | Result |
|---|---|
| The claim lands on compono-api but the connection drops before the bot reads the answer | short alert «Не получилось подключить телевизор», question keeps its buttons, no `#EventError`; the TV still gets exactly the user's URL |
| Same, then the user taps again before the TV polls | «Готово, телевизор подключится…» (idempotent 200), TV paired |
| The connection drops before the claim reaches compono-api | alert, code still pending on the API, next tap pairs |
| Typed look-alike codes (2 cases) | ordinary main menu, no TV question, no claim |
| Bot log scan | no full code, no URL |

Mutation check (`qa-r3/mutate_r3.sh`, `qa-r3/mutation-r3-shop.txt`): 4 of 4 caught (network error
reported as attached; network error escaping the client; failure alert editing the question; the
round-3 regex bug put back).

### Gates

| Gate | Result |
|---|---|
| `ruff check src/`, `ruff format --check src/` | pass, 202 files formatted |
| `pytest tests/` | 1390 passed, 5 skipped (the five opt-in e2e modules), 0 failed (before: 1383 passed) |
| whole `tests/e2e` with tgmock, Redis 7.4.1 and the real compono-api binary (round-3 API fix) | 47 passed, 0 failed (`qa-r3/e2e-all-real-api.txt`) |

### Not tested in round 3, and why

- Real Telegram clients and the stage bot: nothing deployed.
- How long real Telegram accepts a callback answer after a slow claim (compono-api waits up to
  15 s for billing, the bot's client up to 30 s): tgmock accepts any delay. A late answer is
  already handled as a stale callback (no `#EventError`).
- Still open from round 2: the owner's real subscription token in `tests/test_menu_getter.py` and
  `tests/test_subscription_service.py` on main (not changed here).

## QA round 4 (2026-11-18, separate QA worktree from a7e2f78)

### Bug: a slow claim left the user with no answer at all

The claim can take longer than Telegram keeps a callback query answerable: compono-api waits up to
15 s for billing, the bot's client waits up to 30 s for the API, and a hung Redis adds about 12 s
per API call. Telegram then refuses `answerCallbackQuery` with "query is too old and response
timeout expired or query ID is invalid". The error middleware (shop v0.61.4) treats that as
benign, which round 3 counted as handled, but two TV paths depended on the answer:

- 429 and errors (502 billing, 503, network) were shown only as that alert. Refused, the user saw
  nothing after waiting, and did not know to tap again.
- On 422 the answer came before `open_checkout`; the refusal stopped the handler, so the plan list
  never opened (the explanation message had already been sent).

Fix (`src/bot/routers/extra/tv_pair.py` `_answer`): every answer in the confirm handler goes
through one helper. A stale refusal is logged as a warning; a late alert is sent as a chat
message instead (`message.answer`, or `bot.send_message` to the user when the message is
inaccessible); any other `TelegramBadRequest` still raises.

Tests: `TestSlowClaimStaleAnswer` in `tests/test_tv_pair.py` (8 cases, 7 failed before the fix:
`qa-r4/stale-answer-unit-before-fix.txt`). E2E `tests/e2e/test_tv_pair_qa4_e2e.py` (real bot,
tgmock with `answerCallbackQuery` refused as too old, claim delayed 1.5 s): late 502 reaches the user
as a message and the next tap pairs; late 422 still opens the plan list; late attach sends no extra
message. The first two failed on the old handler (`qa-r4/qa4-e2e-before-fix.txt`) and pass after the
fix. Telegram's exact answer window is not documented; tgmock has no clock, so the refusal is
injected rather than timed.

Also fixed: the one `PLC0415` ruff finding in `tests/test_tv_pair.py` (an import inside a test).

### Gates

| Gate | Result |
|---|---|
| `ruff check src/`, `ruff format --check src/` | pass, 202 files formatted |
| `ruff check` / `ruff format --check` on the changed test files | pass (the new e2e module has `print` like the other e2e modules) |
| `pytest tests/` | 1398 passed, 6 skipped (opt-in e2e), 0 failed |
| whole `tests/e2e` with tgmock, Redis 7.4.1 and the real compono-api binary from QA round 4 (API commit with the constant-time secret check) | 50 passed, 0 failed (`qa-r4/e2e-all-real-api.txt`; round 3: 47) |

## QA round 5 (2026-11-18, separate QA worktree from cdf4867)

### The branch no longer merged into main

`main` moved 25 commits ahead (the Stars-only payments work, up to 92a204c) and both sides had
changed `FakeBilling.__init__` in `tests/e2e/fake_billing.py`, so PR #13 had a merge conflict.
`main` was merged into the branch (a normal merge commit, no rebase, no force-push); the conflict
was resolved by keeping both sets of fields. The merge also brings main's Stars-only e2e modules into
this branch's e2e run, including the button crawl that checks no screen names rubles, cards, SBP
or the website; the TV pairing texts name none of them.

### Fixed: the question deleted while the claim runs

The claim can take many seconds (round 4). If the user deletes the «Подключить телевизор?»
message meanwhile, Telegram refuses `editMessageText` with "message to edit not found" (or "message
can't be edited"). The claim had already happened, so the TV pairs, but that refusal escaped
`_edit`: the tap was never answered and the user saw nothing (on the real bot with tgmock, no
screen at all after the tap). Fix (`src/bot/routers/extra/tv_pair.py` `_edit`): for those two
refusals the outcome is sent as a new message; "message is not modified" is still ignored; any
other `TelegramBadRequest` still raises (the round 1 test that pinned "message to edit not found"
as raising now uses a "can't parse entities" error).

Tests: `TestQuestionGoneDuringClaim` in `tests/test_tv_pair.py` (7 cases: attached, expired and
used, each with both refusals, plus cancel), all 7 failed before the fix
(`qa-r5/deleted-question-unit-before-fix.txt`). E2E `tests/e2e/test_tv_pair_qa5_e2e.py` (real bot,
tgmock with `editMessageText` refused, real compono-api binary with the round 5 API fix): both
cases failed on the old handler (`qa-r5/qa5-e2e-before-fix.txt`: no screen after the tap) and pass
after the fix (`qa-r5/qa5-e2e-after-fix.txt`: «Готово…» arrives as a new message, the TV poll
returns `paired`, no `#EventError`). tgmock does not track deleted messages, so the refusal is
injected.

Not changed, noted: with `rules_required` or `channel_required` switched on, a new user's
`/start tv-<CODE>` is answered with the rules or channel prompt and the code is not asked about
again after accepting. Every deep link behaves this way, and both settings are off in prod.

### Gates (tree after the merge and the fix)

| Gate | Result |
|---|---|
| `ruff check src/`, `ruff format --check src/` | pass, 207 files formatted |
| `ruff check` / `ruff format --check` on `tests/test_tv_pair.py` and the new e2e module | pass, except `T201 print` in the e2e module, like every other e2e module |
| `pytest tests/` | 1528 passed, 10 skipped (opt-in e2e), 0 failed |
| the six TV pairing e2e modules, real compono-api binary from API commit 4f44f83 (round 5 cancel fix) | 46 passed, 0 failed (`qa-r5/e2e-tv-real-api.txt`) |
| whole `tests/e2e` (TV modules plus main's stale-callback and Stars-only modules, crawl included), tgmock, Redis 7.4.1, the same API binary | 84 passed, 0 failed in 28 min (`qa-r5/e2e-all-real-api.txt`) |


## QA round 6 (2026-11-18, separate QA worktree from 2b5777c)

### Fixed: a tap that arrives with an InaccessibleMessage got no answer text

Since Bot API 7.0 `callback_query.message` can be an `InaccessibleMessage` (`date` 0, no text):
"deleted or otherwise inaccessible", for example a message too old for Telegram to send its
content (no exact age threshold is documented). `_edit` returned silently when the message was
not a `Message`, while `_send_no_subscription` and `_answer` already fell back to a new message.
So for such a tap the claim ran (the TV paired), but «Готово», «Код устарел», «уже использован»
and «Отменено» never reached the user. On the real bot with tgmock and the real compono-api the
user saw no screen at all after the tap. Fix (`src/bot/routers/extra/tv_pair.py` `_edit`): the
outcome is sent with `bot.send_message` to the user who tapped.

Tests: `TestInaccessibleQuestion` in `tests/test_tv_pair.py` (attached, expired, used, cancel),
4 of 4 failed before the fix (`qa-r6/inaccessible-unit-before-fix.txt`). E2E
`tests/e2e/test_tv_pair_qa6_e2e.py` (real bot, tgmock, real compono-api binary built from 4f44f83;
the update carries `{"chat", "message_id", "date": 0}`): the three outcome cases failed on the old
handler (`qa-r6/qa6-e2e-before-fix.txt`, no screen after the tap). After the fix all four pass,
including a user without a subscription, where the retry message is sent and the plan list
opens through aiogram-dialog (`qa-r6/qa6-e2e-after-fix.txt`). The TV poll returns `paired` and no
`#EventError` is sent.

Not changed, noted: if the user scanned the same code twice and pairs from one question,
«Отмена» on the other still says «Отменено. Телевизор не подключён.» although the TV is paired.

### Gates

| Gate | Result |
|---|---|
| `ruff check src/`, `ruff format --check src/` | pass, 207 files formatted |
| `ruff` on `tests/test_tv_pair.py` and the new e2e module | pass, except `T201 print` in the e2e module, like every other e2e module |
| `pytest tests/` | 1532 passed, 11 skipped (opt-in e2e), 0 failed |
| compono-api 4f44f83 (unchanged this round): `go vet ./...`, `go test -race` of the TV pairing, billing, redis and middleware packages | clean, all ok |
| whole `tests/e2e` (all TV modules including qa6, plus the stale-callback and Stars-only modules), tgmock, Redis 7.4.1, real compono-api binary from 4f44f83 | 88 passed, 0 failed in 28 min 52 s (`qa-r6/e2e-all-real-api.txt`) |

## QA round 7 (2026-11-18, separate QA worktree from ee20566)

### Fixed: a flaky test made CI red (no change to the bot itself)

The docs-only push b4f2388 failed CI (`lint-and-test`, run 53). The Forgejo actions logs (read
only) show the same file broke the other two red runs as well: run 53
`test_press_after_storage_loss_recovers_and_new_menu_works` (`assert new_data != old_data`, the
recovery menu was not sent yet), runs 50 (this PR) and 46 (PR #12)
`test_press_after_stack_reset_recovers_into_fresh_menu` (`assert 1 == 0`)
(`qa-r7/ci-run53-excerpt.txt`). Locally the full suite failed the same way in 1 of 21 runs. Cause:
the test harness waited a fixed 100 ms (`settle`) for work that aiogram-dialog runs in background
tasks (the `BgManager` menu start and the recovery). On a busy runner that is not enough.

- New test `test_recovery_is_awaited_even_when_telegram_is_slow` makes every fake Telegram call
  take 150 ms. Before the fix it failed (`qa-r7/lost-context-flake-before-fix.txt`, `IndexError`:
  no menu sent yet); after it passes (`qa-r7/lost-context-flake-after-fix.txt`).
- Fix (test code only): `settle()` waits until no other asyncio task is running, twice in a row,
  with a 10 s limit that fails the test with the list of running tasks.
- After the fix the full suite passed 10 of 10 local runs.

The file is not part of the TV feature (it came with COM-180), but its flake turned this PR's CI
red, so the fix rides in this PR.

### Checks

No new bug found in the bot code. What was checked beyond rounds 1-6:

- **Code review again** of `src/bot/routers/extra/tv_pair.py`, `src/services/tv_pair.py`, the
  `/start tv-` handler, `ApiClient.claim_tv_pair` and the middlewares a TV update passes through.
  `AccessMiddleware` stops a blocked user before the handler, so a blocked user cannot pair.
  `GarbageMiddleware` deletes the user's own `/start tv-<CODE>` message, as it does for every
  `/start` with a payload; the bot's question still arrives. The global `PrivateFilter` keeps the
  question out of group chats. `decode_start_param` returns nothing for `tv-`, so the full code
  never lands in `users.source`, billing attribution or the `#EventNewUser` card.
- **Noted, wording (same family as the round 6 note on «Отмена»):** if the user scanned the same
  code twice, paired from one question and then taps «Подключить» on the other, the TV has already
  redeemed and compono-api answers 404, so the bot says «Код устарел. Обновите его на телевизоре…»
  although the TV is connected. compono-api deliberately does not tell a redeemed code from an
  expired one. Found by reading the code, not run.
- **Not a bug:** `_CODE_RE` uses `$`, which also matches before a trailing newline, so forged
  callback data `tvp:K7M4QX9P\n` passes; compono-api trims it and claims the same code, and only the
  first two characters are logged.

### Gates

| Gate | Result |
|---|---|
| `ruff check src/`, `ruff format --check src/` | pass, 205 files already formatted |
| `ruff check` and `ruff format --check` on `tests/test_lost_context_recovery.py` | pass |
| `pytest tests/` on ee20566 | 1532 passed, 11 skipped (opt-in e2e), 0 failed |
| `pytest tests/` with the flake fix, 10 runs in a row | 1533 passed, 11 skipped, 0 failed each time |
| the seven TV e2e modules (`test_tv_pair_e2e.py`, `_qa_` and `_qa2_` to `_qa6_`), tgmock, Redis 7.4.1, real compono-api binary built from 4f44f83 with go1.26.10 | 50 passed, 0 failed in 6 min 28 s (`qa-r7/tv-e2e-real-api.txt`); no subscription URL, connect link or internal secret in the output |
| compono-api 4f44f83: `go test -race ./...`, golangci-lint v2.10.1 (go1.26.10) | 1531 passed; 0 issues (see the API PR's QA round 7 section) |

## QA round 8 (2026-11-18, separate QA worktree from e37b168)

### Fixed: the TV link was swallowed after the cancel survey's «Другое»

After a cancelled payment the bot asks why. «Другое» sets `cancel_survey_awaiting_text:<tg>` for
30 minutes, and `AwaitingCancelSurveyText` (router `extra.cancel_survey`, which runs before
`menu.handlers`) took **every** message in that time as the answer, commands included. A user who
then scanned the TV's QR code got «🙏 Спасибо за ответ!» instead of the confirmation question, so the
TV could not pair. The full `/start tv-<CODE>` text was also stored as the answer for 90 days and
sent to the admin chat (`ntf-event-cancel-survey-other`). A plain `/start` was swallowed the same way.

- Unit tests `TestAwaitingCancelSurveyTextSkipsCommands` (`tests/test_cancel_survey_router.py`):
  3 of 4 failed before the fix (`qa-r8/cancel-survey-unit-before-fix.txt`). The fourth checks that a
  typed answer is still taken.
- tgmock e2e `tests/e2e/test_tv_pair_qa8_e2e.py` on the real bot and the real compono-api binary
  (ebfeaf8): the TV link and plain /start cases failed before the fix
  (`qa-r8/qa8-e2e-before-fix.txt`, codes redacted). After it all 3 pass: the TV poll returns
  `paired`, and the full code is not in the admin chat, the bot log or the stored answer
  (`qa-r8/qa8-e2e-after-fix.txt`).
- Fix: a message whose text starts with `/` is never the free-text answer.

### Noted, not changed

- A claim in the last seconds of the 10 minutes is answered «Готово», but the TV polls every 3 s
  and can find the code expired (410) before its next poll. The contract says the lifetime is
  never extended; same family as owner item 9.
- `ApiClient.claim_tv_pair` maps any 200 to "attached" without reading the body, and a 200 with a
  non-JSON body raises. Only a misrouted `APP_API_URL` would send that.

### Gates

| Gate | Result |
|---|---|
| `ruff check src/`, `ruff format --check src/` | pass, 205 files already formatted |
| `pytest tests/` | 1537 passed, 12 skipped (opt-in e2e), 0 failed |
| the eight TV e2e modules plus `test_stale_callback_e2e.py`, tgmock, Redis 7.4.1, real compono-api built from ebfeaf8 with go1.26.10 | 59 passed, 0 failed in 7 min 26 s (`qa-r8/tv-e2e-real-api.txt`); 0 subscription URLs or full codes in the output |
| compono-api ebfeaf8: `go vet ./...`, `go test -race` on tvpair, usecase, domain, adapter/redis, middleware | clean; all ok |

## Owner defaults, 2026-11-18

Branch `feat/tv-pairing` on top of 4ab66c2 (shop main v0.61.5 is already in it, no rebase needed).

| Default | Tests | Result |
|---|---|---|
| A valid `/start tv-<CODE>` is attributed to `androidtv`; the code never reaches `users.source`, the touch or the admin line; malformed `tv-` payloads stay unattributed; a returning user gets `{"ref":"androidtv"}` as last touch | `tests/test_attribution.py::TestAndroidTvDeepLinkAttribution`, `TestAttributionIsUntouched::test_tv_payload_decodes_to_androidtv_without_the_code`; e2e `test_new_user_via_tv_link_is_attributed_to_androidtv` (billing `POST /users` body has source `androidtv`, first and last touch `{"ref":"androidtv"}`, no code) | pass |
| After a claim: «✅ Готово. Телевизор попросит подтвердить подключение — подтвердите его пультом.» (no "через несколько секунд") | `TestCopy::test_result_texts`, `TestCopy::test_attached_text_does_not_promise_an_automatic_connection`; every e2e that checked the old text now checks the new one | pass |
| compono-api per-IP create limit 30 / 10 min | compono-api PR #3 | see that PR |

The new unit tests failed before the change (`test-evidence/tv-pairing/defaults-2026-11-18/unit-before-fix.txt`) and pass
after it (`unit-after-fix.txt`). Full e2e with the real compono-api binary built from compono-api `feat/tv-pairing` 1f66744
(limit 30): `e2e-all-real-api.txt`, 91 passed, 0 failed in 29 min; `e2e-androidtv-real-api.txt` shows the billing create-user body for a new TV user. Unit suite: 1542 passed, 12 skipped; ruff check and format clean.
