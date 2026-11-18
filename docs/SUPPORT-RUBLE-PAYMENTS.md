# Support: people who want to pay in rubles

Why: Telegram's bot terms (§6.2) allow digital goods to be sold in a bot only for Telegram Stars, and a bot that uses
other payment systems can be shut down. So @compono_bot takes Stars only and says
«Оплата в рублях сейчас недоступна. Если хотите оплатить в рублях — напишите в @compono_support.»
The bot itself never links the website as a way to pay. A person at @compono_support sends the reply below.

Facts behind the template (checked 2026-11-17):
- `https://componovpn.com/pricing` and `https://ru.componovpn.com/pricing` both answer 200.
- Web checkout on componovpn.com creates a Platega (СБП) order: a test order for Старт / 30 days returned a payment id,
  a `pay.platega.io` payment link and a claim token, with no redirect.
- After payment the site shows the connection steps on the success page, and billing emails the buyer a button that
  opens `/connect/<token>` (the same page the bot's «Подключиться» opens).
- `app.componovpn.com` is the account page; sign-in is a code sent to the email used at checkout.

## Reply template (paste as is)

```
Здравствуйте! В боте сейчас можно оплатить только звёздами Telegram. В рублях (СБП) можно оплатить на сайте:

https://componovpn.com/pricing

Если сайт не открывается, используйте зеркало: https://ru.componovpn.com/pricing

Как это работает:
1. Выберите тариф и срок, укажите email и оплатите.
2. Сразу после оплаты на сайте откроется страница с инструкцией и кнопкой подключения.
3. Та же ссылка придёт на ваш email (проверьте папку «Спам»). Подписку потом можно найти в личном кабинете https://app.componovpn.com — вход по коду на тот же email.

Если оплатили, а ссылка не пришла, пришлите сюда email, который указали при оплате, и мы поможем.
```

## Short version (for a quick reply)

```
В боте сейчас только оплата звёздами. В рублях — на сайте: https://componovpn.com/pricing (если не открывается: https://ru.componovpn.com/pricing). После оплаты ссылка для подключения появится на сайте и придёт на email.
```

## Notes for support

- A web purchase is tied to the email, not to the Telegram account. The bot will not show that subscription as the
  user's own; the user connects through the `/connect` link from the site or the email.
- Unverified: whether a site payment extends a subscription the person already has from the bot. Web orders are matched
  by email; bot subscriptions by Telegram id. If the person ends up with two links, ask which one they use.
- Never send a subscription link to anyone except the email owner; the link is the access key.
- Refunds follow the 7-day rule in `src/compono/CLAUDE.md` "Refund runbook".
