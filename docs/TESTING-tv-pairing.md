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
| No subscription → «нужна активная подписка», retry button kept, plan list opened; the code stays pending; after buying, the retry attaches | unit + e2e (real API) | pass | `test_no_subscription_opens_plans_and_keeps_a_retry`; e2e `test_user_without_subscription_gets_plans_then_retries` |
| Code already claimed by someone else → «Этот код уже использован» | unit + e2e | pass | `test_final_answers_remove_the_buttons`; e2e `test_code_used_by_someone_else` |
| Unknown or expired code → «Код устарел» | unit + e2e | pass | same; e2e `test_expired_or_unknown_code` |
| 429 and failures (network, 400, 401, 5xx, non-JSON body) → alert, question and buttons kept | unit | pass | `test_transient_answers_keep_the_question`, `TestClaimClient` |
| Malformed or forged button data never reaches the API | unit | pass | `test_malformed_button_never_calls_the_api`, `TestCallbackData` |
| Cancel → «Отменено», no claim, TV still pending | unit + e2e | pass | `TestCancelHandler`; e2e `test_cancel_does_not_claim` |
| Plain `/start` still opens the main menu | e2e | pass | `test_plain_start_still_opens_main_menu`; existing e2e |
| API client: exact path, header, body; every status mapped; network error → FAILED without raising | unit (httpx MockTransport) | pass | `TestClaimClient` |
| Logs: the code never appears; 404 is logged at INFO, 503 at ERROR; shop log of the e2e has no full code | unit + e2e | pass | `test_logs_never_carry_the_code_and_expected_answers_are_not_errors`; e2e asserts `code not in shop.log()` |
| Russian copy rendered with the real fluent files: contract sentences present, no price in the bot's new texts, alert texts within 200 chars | unit | pass | `TestCopy` |
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
