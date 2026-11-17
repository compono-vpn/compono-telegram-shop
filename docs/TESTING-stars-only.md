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

## Release order

1. Merge, stage sync, then walk the flows above on @compono_dev_bot.
2. Prod shop sync. Check that no ₽ appears and no Platega link shows in the bot.
3. Prod: `update billing.payment_gateways set is_active=false where id=7;` (PLATEGA BOT). Once this release is live, the
   bot already ignores the row, so this is clean-up, not a switch. Leave WEB row 8 alone, then smoke the web checkout
   again.
4. Rollback: the argocd shop tag goes back to the previous version (v0.61.4). Billing rows need no change.
