# Public Telegram proxy access

Visitors can use the public Telegram Desktop proxies without starting a VPN trial.
`/start proxy` and the existing `/start source-channel_proxy` route directly to the
proxy window; source attribution remains handled by the existing middleware.
The VPN offer leads back to the ordinary menu, where trial eligibility is checked
and the user must explicitly choose to start a trial. Opening proxies provisions
nothing and sends no separate channel prompt.

Both proxy entry points request plan 0 for absent, expired, disabled or trial
subscriptions. Only an active non-trial subscription passes its plan ID. Billing
must already enforce the new explicit `is_public` policy before this shop release
is deployed. The current two public WEB hosts remain available; no new proxy is
provisioned and no paid MTProto service is promised.

Rollout: billing migration 21 and billing API first; verify plan 0 returns only
public rows, then deploy this shop release. Roll back the shop first if rolling
back billing to the former API where plan 0 meant all active proxies. Keep the
additive database column in place during an application rollback.
