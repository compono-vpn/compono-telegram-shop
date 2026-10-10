# Daily activity reporting (COM159, 2026-10-10)

The existing daily admin report now distinguishes profile requests from VPN
latest-seen activity. Profile requests include automatic refreshes and failed
profile generation. The API excludes its known Go monitoring user agent, but
other automation may remain. Counts cover all accounts, not one signup cohort.
The previous Connected label incorrectly suggested historical daily usage;
latest online_at can move to a later day and lower the earlier day's count.

The new API client requires a nonnegative integer profile_requesters response;
missing/malformed responses follow the existing error notification path instead
of showing a misleading zero. Recipient, cron, payment logic, trial grants,
customer notifications and paid-offer traffic gate are unchanged.

Deployment order: API PR34 first, verify /stats/profile-requesters with service
authentication and compare aggregate against read-only SQL, then release shop.
Rollback shop to v0.49.0 before removing the new API endpoint. No migration.
Do not invoke the live scheduled send as a smoke test; render locally or in an
isolated short-lived process, avoiding the serving bot's memory budget.

Verification: new client/report tests reproduced missing implementation, then
29 focused tests passed. Full suite: 794 tests passed. Source lint and format checks passed.
The initial full run used a stale shared environment (old aiogram); repeat uses
the worktree's frozen uv lock/environment. No dependency or lock changes.

This does not implement immutable historical VPN activity or calculate conversion
rates. COM159 stays in progress until the remaining reporting scope is resolved.
