# compono-telegram-shop

Python aiogram 3 + aiogram-dialog 2.6 + dishka bot. Checks before merge (CI runs only on push to `main`):
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
