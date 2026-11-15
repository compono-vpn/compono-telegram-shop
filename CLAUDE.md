# compono-telegram-shop

Python aiogram 3 + aiogram-dialog 2.6 + dishka bot. Checks before merge (CI runs on pull requests and on push to `main`):
`ruff check src/`, `ruff format --check src/`, `pytest tests/`.

## Lost dialog context (2026-11-07)

Every inline keyboard carries an aiogram-dialog intent id. If its context is gone from Redis (a Redis flush,
a `StartMode.RESET_STACK` from another path, a lost stack) the press raises `UnknownIntent`.
`src/bot/routers/extra/error.py` `on_lost_context` now recovers instead of only showing an error: it answers the
callback, strips the dead keyboard from that message, starts `MainMenu.MAIN` in `RESET_STACK` through
`BgManagerFactory`, and shows `ntf-menu-refreshed` («Меню обновлено»). Only if the restart itself raises does the
user still see `ntf-error-lost-context`. Test: `tests/test_lost_context_recovery.py` (real dispatcher and
aiogram-dialog, fake Bot session).

- FSM keys are `fsm:<bot_id>:<chat>:<user>:aiogd:{stack,context}:...` in Redis db0 with no TTL. Few of them
  (about 10 for the whole user base) means the db was flushed or the contexts were reset, not that they expired.
- Reminders and expiry notices are plain messages (`NotificationService`) and never touch the dialog stack.
  The `redirect_to_*` taskiq tasks and the Kafka `redirect` handler do start dialogs in `RESET_STACK` with
  `DELETE_AND_SEND`; that replaces the old menu on purpose after a payment or trial result.

## Telegram unreachable for a moment (2026-11-09)

One TCP reset on connect to `api.telegram.org` used to surface as `#EventError` and, in the 2 h not-connected
reminder task, lose that user's reminder (the task removes the entry from the Redis set before sending).
`src/services/telegram_connect_retry.py` `ConnectRetryMiddleware` is installed on the bot session in `BotProvider`
(bot pods and taskiq worker): a request whose connection never opened (`ClientConnectorError`) is retried after 0.5 s
and 2 s. Timeouts and resets after the request was sent are not retried, because Telegram may already have delivered
the message. If the reminder send still fails with `TelegramNetworkError`, the task puts the entry back for 5 minutes
later (`NOT_CONNECTED_RETRY_DELAY`) and logs a warning instead of raising. Tests: `tests/test_telegram_connect_retry.py`,
`tests/test_notification_delivery_failures.py`. The worker talks to `api.telegram.org` directly, not to the in-cluster
Bot API server.

## Message widgets: connect card, subscription card, plan card (COM-182, 2026-11-09)

Bot API 10.4 message widgets (HTML cards inside a message, private chat only). Behind `APP_WIDGETS_ENABLED`
(default off; on only in stage values). `src/services/widgets.py` `WidgetService` + HTML in `src/services/widget_cards/`.

- "🚀 Подключиться" sends the connect card (one "Подключить" button opening `{website_url}/connect/<token>`, a copy-link
  button, a status pill that turns "подключено" by itself: the card asks the bot `chk` every 15 s while on screen and the
  bot edits `chat_data` once Remnawave shows a device, traffic or a subscription fetch).
- "💳 Подписка" sends the status card (plan, days left, traffic bar; "Продлить" sends the plan card, "Другие действия"
  opens the old Subscription dialog) to a paid subscriber, and the plan card to everyone else.
- Plan card: plan tabs, durations with prices from billing, "Оплатить N ₽" asks the bot `pay:<plan>:<days>`; the bot
  creates the payment (Platega, else the first active ruble BOT gateway; `star:` = Telegram Stars invoice) and answers
  the link, then a second tap opens it (Telegram only allows opening a link on a fresh tap).
- aiogram 3.30 knows nothing of widgets: the methods are local `TelegramMethod` classes, and `widget_query` updates are
  taken out of `update.model_extra` in `src/api/endpoints/telegram.py` and answered before they reach the dispatcher.
  `lifespan.py` adds `widget_query` to `allowed_updates` when the flag is on. Limits: HTML 4 KB after zlib, state 1 KB,
  answer 1 KB, request data 64 bytes; `tests/test_widgets.py` checks them.
- Any failure falls back to the old screens; old Telegram apps show only the caption (`msg-widget-card-caption`).

### TON from the plan card (COM-183, 2026-11-09)

Gateway type and currency `TON` exist in the shop (enums) but are kept out of the old dialog payment screens
(`WIDGET_ONLY_GATEWAYS` in `subscription/getters.py`): only the widget can pay with them. The plan card shows
"Оплатить TON" when billing has an active TON gateway and the user's Telegram has a wallet (`TelegramWidget.wallet`).
Tap → `ton:<plan>:<days>` with the user's wallet → billing creates the payment and returns
`ton://transfer/<address>?amount=<nanotons>&text=<payment id>` → the bot answers a TON Connect transaction (comment cell
built in `src/services/ton.py`, byte-identical to tonsdk) → the widget calls `wallet.sendTransaction(tx, "tp:<id>")` →
the bot gets a `sent_transaction` query and asks billing `POST /payments/ton/confirm` up to 4 times 3 s apart; billing's
own poller finishes the payment if the chain is slower. Stage receiving wallet: Vault `kv/compono-ton-stage-wallet`.

## Payment recovery, offers, survey (COM-190, COM-192, COM-194, 2026-11-15)

- **Nudge (COM-190).** Every payment link made in `_create_payment_and_get_data` is queued by
  `src/services/payment_nudge.py` `schedule_payment_nudge` (Redis zset `pending_payment_nudge`, due +5 min; payment link,
  plan and price in `payment_nudge_data:<id>`). Cron `* * * * *` (`tasks/payment_nudge.py`) sends one persistent message
  «Оплата не завершена» with «Оплатить» (the same link) and «Другой способ» (`pn:<payment id>` →
  `routers/extra/payment_nudge.py` reopens `Subscription.PAYMENT_METHOD` for the same plan and period through
  `checkout_entry.open_checkout`). Sent only while billing says PENDING, never after the user paid something since, only
  for the user's newest payment (`payment_nudge_latest`), once per payment (`payment_nudge_sent`), once per 30 min per
  user (`payment_nudge_user`); a send later than 15 min after its due time is dropped. The old self-deleting 15 minute
  reminder (`ntf-event-cancel-survey-pending`) is gone; the cancel survey itself is unchanged. Widget payments
  (`WidgetService`, flag off in prod) and the proxy purchase are not queued. Metric `bot_payment_nudge_sent_total{gateway}`.
- **Offer (COM-192).** One 30% first-month discount per user, ever, only for users we would lose: (a) trial expired and
  never paid, in the expiry notice (`notify_subscription_expired` → `ntf-event-user-expired-offer`); (b) an abandoned
  payment, 15 min after creation (`process_due_payment_offers`, zset `pending_recovery_offer`, `ntf-recovery-offer`).
  The once-ever guard is the billing claim `user_reminders(kind='RETURN_OFFER', dedup_key='v1')`; paid users are never
  claimed (`services/recovery_offer.py has_paid`: a COMPLETED payment above 0, or an active non-trial subscription). The
  button `ro:<payment id|->` (`routers/extra/recovery_offer.py`) activates billing promocode `RETURN30`
  (PURCHASE_DISCOUNT 30, `purchase_discount_max_days` 30, availability NEW, unlimited activations, no expiry — one row per
  environment, created by hand in `billing.promocodes`) and opens the plan list, or the durations of the abandoned plan.
  Billing applies the discount only to durations up to 30 days and clears it after the first completed purchase, so
  renewals are full price. Nothing is auto-applied and nobody is asked to type a code: the COMPONO30 hints are gone from
  the 1-day notice and the check-in (the COMPONO30 code itself still works if typed). Known edge: the discount stays on a
  user who never buys, and a proxy purchase (plan 5, 30 days) can consume it without clearing it. Metrics
  `bot_recovery_offer_sent_total{source}`, `bot_recovery_offer_accepted_total{source}`.
- **Prices and terms (COM-192).** Plan screen lines: «Старт — 119 ₽/мес · 100 ГБ, 2 устройства» (`plans_getter`, price
  from billing `calculate_price` for 30 days, struck-through old price when discounted). First screen for users who can
  take the trial: «Бесплатный пробник: 2 дня, 5 ГБ, 1 устройство … Дальше VPN от 119 ₽/мес» (`services/first_screen.py`,
  read from the trial plan and the cheapest 30-day price). The trial screen has «💳 Купить подписку» (same
  `on_subscription_plans` purchase flow).
- **Source survey (COM-194).** Asked right after «✅ Оплата прошла успешно!» (`redirect_to_successed_payment_task`),
  not after the trial. Eligibility unchanged (`services/source_survey.py`): no source tag, no referral, account up to 7
  days old, once per user. «Другое» is a one-tap answer; there is no free-text step, so a typed promocode is never taken
  as survey text.
