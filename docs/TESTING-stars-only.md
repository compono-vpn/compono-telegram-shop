# Testing: the bot sells for Telegram Stars only

Why: Telegram's bot terms (section 6.2) allow digital goods in a bot to be sold only for Telegram Stars. A bot that uses
other payment systems can be shut down. Rubles are sold on componovpn.com. The bot never names the website as a way to
pay. When someone wants to pay in rubles, the bot says «Оплата в рублях сейчас недоступна. Если хотите оплатить в
рублях — напишите в @compono_support.» A person at support then sends `docs/SUPPORT-RUBLE-PAYMENTS.md`.

## What the code does

- `src/services/bot_payments.py` holds the rule. `bot_gateways()` keeps a billing gateway row only when it is active, on
  channel BOT or ALL, and of type TELEGRAM_STARS. Every checkout path uses it: the payment method screen, the confirm
  screen, plan/duration selection, the trial 30-day shortcut and the widgets. Billing may still return PLATEGA (prod row
  7 is active today), PLATEGA_CRYPTO, TON or YooKassa. The bot ignores those rows whatever `is_active` says.
- `_create_payment_and_get_data` refuses any non-Stars gateway before it calls billing. A forged method press or a stale
  dialog cannot create a ruble payment. The crypto (Plaidly) handlers return without doing anything.
- Prices in the bot are read in XTR, not in billing's `default_currency` (RUB in prod). This covers the plan list, the
  durations, the first screen («Дальше VPN от 119 ★/мес») and the checkout.
- Proxy (plan 5): a Stars payment. The menu price is the plan's 30-day XTR price. The invoice charges what billing
  recorded on the transaction, because billing prices proxy payments without user discounts. With no XTR price, there
  is no buy button. The old «<s>49 ₽</s> … до 31 октября» text is gone.
- Payment nudge: kept for Stars, because an invoice link the user closed can still be paid. Billing's 5-minute check
  still applies (PENDING, newest payment, no payment since then). The «Другой способ» button is gone. Old messages that
  still have it open the Stars-only checkout. A pending non-Stars payment queued before the release, such as an old
  Platega link, is never resent.
- Recovery offer and the expired-trial offer: kept. The copy now says to pay with Stars. The button activates RETURN30
  and opens the Stars checkout. Billing applies the 30% to the XTR price and rounds down to whole stars.
- Widgets: the plan card shows ruble and TON prices, so it is off (`PLAN_CARD_ENABLED = False`). «Подписка» and
  «Продлить» open the ordinary Stars checkout. `pick_gateway` answers only `star`. The flag stays off in prod anyway.
- `/start web_<token>` opens the main menu with no website message. The yookassa donate button on the dev-only
  remnashop card is gone. The cancel-survey option «Карта не прошла» is now «Оплата не прошла» (same reason code).
- Not touched: billing and its webhooks. A user who still holds an old Platega link can pay it. The Platega webhook
  reaches billing, billing completes the payment and the shop's Kafka consumer shows the success screen, as before.
  The shop has no payment webhook endpoint of its own.

## Checks

```
uv run ruff check src/
uv run ruff format --check src/
uv run pytest tests/                     # 1324 passed, 2 skipped (the two e2e modules)
uv pip install -e ../../tgmock          # from the repo root: path to src/compono/tgmock
SHOP_E2E=1 SHOP_E2E_REDIS_SERVER=/opt/homebrew/bin/redis-server uv run --no-sync pytest tests/e2e -v -s   # 13 passed
```

Unit tests: `tests/test_stars_only.py` covers the gateway filter, the checkout handlers and getters, and a lint over the
user-facing ru texts (no ₽, СБП, карта, крипт, Platega, componovpn.com, /pricing or /purchase). Updated tests: payment
nudge, nudge wiring, proxy purchase and screen, widgets, plan prices, first screen, crypto assets, cancel survey, Stars
invoice, `/start web_`.

E2E (`tests/e2e/test_stars_only_e2e.py`): the real bot runs against tgmock and the fake billing. Billing is given the
prod rows (PLATEGA BOT active, PLATEGA WEB, PLATEGA_CRYPTO BOT) on top of the stage rows (Stars ALL, YooKassa BOT, TON).
Flows covered:

1. /start → Подписка → Купить → plans in ★ → Старт → durations 119/319/579/999★ → confirm. The confirm screen has one
   «⭐ Оплатить звёздами» invoice link (XTR, 119), the ruble line and a @compono_support button. Then
   `pre_checkout_query` and `successful_payment` follow, and billing gets `/payment/handle-free` for the payment.
2. Promo code RETURN30: the plan list shows «<s>119 ★</s> 83 ★/мес» and the invoice is 83 stars.
3. Renewal from the expiry notice button (`gt_purchase_RENEW`) → Продлить → 1 месяц → Stars invoice with RENEW.
4. Proxy: `/start proxy` → «⭐ Pro за 49 ★» → invoice for 49 stars on plan 5 → paid.
5. Ultra: plan 38 bought for 799 stars. An Ultra subscriber taps «🌐 Выделенный IP» and gets the Швеция/Нидерланды prompt.
6. Across all flows, every payment billing received was TELEGRAM_STARS in XTR.

Proof that the tests catch broken code (run on 2026-11-17):

- All of `src/` and `assets/` reverted to `forgejo/main`, with the new tests kept: 53 unit tests failed, plus one
  collection error (the new module is missing). 6 of the 7 Stars-only e2e tests failed (the Ultra-prompt one passes on
  old code too).
- Gateway filter reverted to the old rule (BOT/ALL except TON): 18 failures.
- The Stars-only guard in `_create_payment_and_get_data` removed: 7 failures.

## Not covered here

- The country prompt that follows an Ultra payment comes from billing's Kafka `subscription_success` redirect. The e2e
  has no Kafka, so that step is covered by `tests/test_ultra_redirect_offer.py`, not end to end.
- A real Telegram Stars payment. Use stage (@compono_dev_bot): dev accounts' Stars payments are refunded automatically
  (`src/bot/routers/extra/payment.py`).
- Billing's proxy purchase through `/payment/handle-free`. Reading compono-billing `HandlePaymentSucceeded`, the
  proxy path does not depend on the gateway. Unverified on stage.

- Completing a paid order: billing's `/payment/handle-free` only queues a Kafka event, and the payment turns COMPLETED
  a moment later. The bot waits for that (about 20 s) and refunds only a payment billing CANCELED; anything else raises
  `#EventError` and keeps the stars. The e2e fake
  billing completes asynchronously too (0.7 s), but real Kafka lag is unmeasured. On stage, after a Stars payment,
  check that the subscription was granted and the bot did NOT say «Звёзды вернули», and that the log has no
  "charged but billing has it" line.

## QA round 1 (2026-11-18): three money bugs, fixed with failing tests first

- Same invoice paid twice while billing's Kafka consumer is slow: the payment stays PENDING, the pre-checkout passed and
  Telegram took the stars twice for one order (billing completes a payment once). Now the first charge is recorded in
  Redis, the pre-checkout refuses an already charged invoice and a second charge is refunded.
  `tests/test_stars_successful_payment.py`, `tests/test_stars_pre_checkout.py`,
  e2e `test_same_invoice_paid_twice_while_billing_is_slow` (fails on the previous code: pre-checkout said ok).
- «Получить бесплатно» (`purchase_get`) pressed on the confirm screen of a paid order (an older message or a modified
  client; aiogram-dialog ignores `when` when it handles a callback) completed the paid order through handle-free for 0
  stars. `tests/test_free_order_get.py`, e2e `test_hidden_free_button_on_a_paid_order_completes_nothing` (fails on the
  previous code: the Max order completed).
- A rollout cancelled updates still being handled, after the webhook had answered Telegram 200: a successful_payment cut
  off before handle-free lost the order with no refund and no alert. `tests/test_webhook_shutdown_drain.py`.
- Hardening: refund only on CANCELED (not on "not found" or REFUNDED), and the alert names the payment and the charge.

Still not covered: a successful_payment lost before it reaches the bot at all (pod killed hard, Redis/billing down for
30 minutes): billing cancels the PENDING payment and nobody refunds. Reconciling with `getStarTransactions` would catch
it; not built.

## QA round 2 (2026-11-18): two more money bugs, fixed with failing tests first

- A successful_payment within 0.5 s of the user's previous message or tap was dropped by the throttling middleware
  (also by the access, rules and channel gates: a blocked user, RESTRICTED mode, unaccepted rules, a left channel). The
  stars were taken and billing never heard of the order: no handle-free, no refund, no alert. Payment messages now pass
  every gate. `tests/test_payment_message_gates.py` (4 failed on the old code), e2e
  `test_payment_right_after_another_message_still_reaches_billing` (failed on the old code: "User throttled" in the log,
  no handle-free).
- While billing's Kafka consumer lagged, a paid payment stayed PENDING, so 5 minutes later the bot said «Оплата не
  завершена» with the same link and at 15 minutes offered 30% off a new payment. A user who had paid was asked to pay
  again, and both orders completed when billing caught up. Both reminders now skip a payment with a recorded charge.
  `tests/test_payment_nudge.py::TestChargedButNotYetCompleted`,
  `tests/test_recovery_offer.py::TestChargedButNotYetCompletedOffer`.

## QA round 3 (2026-11-18): one more money bug, fixed with a failing test first

- A short billing outage (restart, deploy) when Telegram reported the payment: `UserMiddleware` loads the user from
  billing (it writes the user back with a PUT on every update) before any handler runs. The failure skipped the payment
  handler with its own retries, the #EventError named no payment and no charge, and the stars stayed taken with no
  order. The load is now retried for a payment message (1 s, 3 s) and the final alert names the payment and the charge.
  `tests/test_payment_user_load.py` (2 failed on the old code), e2e
  `test_payment_while_billing_blips_still_reaches_billing` (fake billing answers 503 twice; failed on the old code).

## QA round 4 (2026-11-18): two more gaps in the refund and slow-billing paths, fixed with failing tests first

- A refund the bot owes (a payment billing cancelled, a second charge) that Telegram refuses left the stars taken, and the
  #EventError carried only Telegram's text («TelegramBadRequest: … CHARGE_NOT_FOUND»): no payment, no charge id, so
  nobody could send the stars back by hand. Every refund now goes through `_refund` in `src/bot/routers/extra/payment.py`,
  and a failure raises an alert that starts with the payment, the charge and the user.
  `tests/test_stars_successful_payment.py::test_failed_refund_*` (2 failed on the old code), e2e
  `test_refund_telegram_refuses_alerts_admins_with_the_charge` (tgmock refuses `refundStarPayment`; failed on the old
  code with the bare Telegram error in the alert).
- When billing's Kafka consumer took longer than the bot's ~20 s wait, the user paid, got no «оплата прошла» yet and
  was only sent to the main menu by the error handler, so they could buy the same plan a second time. The bot now says
  «Оплата получена, подписка оформляется… платить ещё раз не нужно» before the admin alert. Nothing is refunded.
  `test_payment_still_pending_tells_the_user_not_to_pay_again`, e2e
  `test_payment_billing_completes_late_tells_the_user_not_to_pay_again` (fake billing completes 28 s after
  handle-free; failed on the old code: the user was told nothing).
- The plan list sold any plan by id. aiogram-dialog's `Select` hands the handler whatever item id the callback carries
  and never checks it against the rendered list, and `on_plan_select` read any plan with `get_plan`. A press from an
  older message or a modified client could start a checkout for a plan not offered to the user: an inactive or
  user-restricted plan (billing's `CreatePayment` checks neither), the proxy plan (recorded undiscounted while the
  invoice used the user's discount) or the trial plan (0 stars, which billing completes by itself). `on_plan_select`
  now takes the plan only from `/plans/available` for this user, the list the screen shows.
  `tests/test_plan_select_guard.py` (3 failed on the old code), e2e `test_plan_not_offered_cannot_be_bought_by_id`
  (failed on the old code: a payment for a hidden 1-star plan was created). Whether Telegram delivers callback data that
  was never on a button is unverified; the older-message case does not depend on it.
- The fake billing now behaves like billing in two more ways: a 0-price payment completes by itself at creation, and
  `/pricing/calculate` applies the user's discount to the proxy plan too (only the recorded proxy payment is
  undiscounted).
- Any user could open the admin dialogs. `goto` (`gt_DashboardUser:MAIN:<id>`, the «Перейти к пользователю» button of
  admin alerts) started any state without a role check, the main menu's «dashboard» button was only hidden by `when`
  (aiogram-dialog still runs it), and nothing inside the dialogs checked the role. From there a user could set their
  own role to DEV (every Stars payment of a DEV is refunded at once while billing still completes the order) or grant
  subscription time. Present on forgejo/main too, not added by this PR. Now `goto` refuses Dashboard states,
  the menu button checks the role (`on_open_dashboard`), and `PrivilegedFilter` sits on the message and callback
  observers of the four admin dialog routers. `tests/test_admin_dialog_access.py` (failed to import on the old code),
  e2e `test_ordinary_user_cannot_open_the_admin_dialogs` (failed on the old code: the user saw «Информация о
  пользователе» and «Панель управления»; the owner still opens the dashboard and «Пользователи»). Needs callback data
  that was never on the user's buttons; whether Telegram delivers such data is unverified, so treat it as reachable.
- Known and left alone: picking a plan with a single duration from the plan list fails with `TypeError: on_duration_select()
  got multiple values for keyword argument 'billing'` (the injected handler is called with explicit dependencies). No plan
  in the prod list has a single duration (checked `componovpn.com/api/v1/plans` 2026-11-18: 1, 2, 3, 38 all have several).

## QA round 5 (2026-11-18)

- The confirm screen could sell a different order than it showed. It reads the invoice link and price from dialog data,
  and a failed payment creation left the previous choice's payment there: pick Макс 1 месяц (confirm, invoice), go back,
  pick Старт 3 месяца while billing fails twice, and the confirm screen said «Старт, 3 месяца, 399★» with the Макс
  1-month invoice behind «Оплатить звёздами». Now `_create_payment_and_get_data` forgets the current payment first
  (`_drop_current_payment`), and the method screen opens the confirm screen only when the new payment exists.
  `tests/test_checkout_payment_state.py::TestFailedCreation`, e2e
  `test_failed_payment_creation_never_offers_the_previous_order` (failed on the old code: the old invoice was offered).
- A payment billing had cancelled was offered again and again. The dialog reuses the payment made earlier for the same
  duration; after billing's 30-60 minute timeout cancelled it, every new pick of that duration gave the same dead
  invoice, which pre-checkout refuses («счёт устарел»), so the user could not pay without leaving the dialog. Now a
  cached payment is reused only while billing says PENDING (`_reusable_payment`); CANCELED, COMPLETED, FAILED or not
  found make a new payment. A PENDING one is kept even when it was already charged, and so is the cached one when
  billing cannot be read, so a new payment never opens a second charge. `TestReuse` (5 failed on the old code), e2e
  `test_checkout_after_billing_cancelled_the_payment_makes_a_new_invoice` (failed on the old code: the cancelled
  invoice was offered again).

## Release order

1. Merge, stage sync, then walk the flows above on @compono_dev_bot.
2. Prod shop sync. Check that no ₽ appears and no Platega link shows in the bot.
3. Prod: `update billing.payment_gateways set is_active=false where id=7;` (PLATEGA BOT). Once this release is live, the
   bot already ignores the row, so this is clean-up, not a switch. Leave WEB row 8 alone, then smoke the web checkout
   again.
4. Rollback: the argocd shop tag goes back to the previous version (v0.61.4). Billing rows need no change.
