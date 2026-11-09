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
