# shop ↔ billing contract (v1)

**BDT-405 / CR-50.** Pins the wire shape that `compono-telegram-shop`'s
`BillingClient` (`src/infrastructure/billing/client.py` +
`src/infrastructure/billing/models.py`) actually depends on when it talks to
`compono-billing`'s internal API (`internal/handler/internal_handler.go`,
mounted under `/api/v1/internal`), plus the one Kafka event schema that
crosses the same boundary (`{env}.compono.notify.user.v1`).

This directory is **checked into both repos, in sync**. It is not code —
nothing imports it at runtime. It exists purely so each side's test suite has
a shared, versioned example of "what billing actually serves" / "what the
shop actually consumes" to test against.

## Layout

```
http/    one fixture per response type, named for the Go domain/port type
         it pins. Field names/casing are the ACTUAL `encoding/json` output
         of that type today (PascalCase where the Go struct has no json
         tags — which is most of them — snake_case where it does).
kafka/   one fixture per event variant on notify.user.v1.
```

## How each side is gated

- **compono-billing** (`internal/contract/contract_test.go`): unmarshals each
  `http/*.json` fixture into the real Go type, re-marshals it, and asserts the
  recursive JSON *shape* (key set + JSON kind per key, at every nesting level)
  of the round-tripped output still equals the fixture's shape. A field
  rename/add/remove/retype in `internal/domain` or `internal/port` flips this
  red. It runs as a normal `go test ./...` package, so it rides the existing
  `test` job in `.github/workflows/ci.yml` — no workflow changes needed.
  `internal/contract/users_test.go` additionally drives the real
  `GET /users` handler (mocked usecase) for both the `?role=` and no-param
  branches and asserts they produce different JSON kinds (array vs object),
  pinning the shape-sniffing seam the shop's client depends on.
  `internal/usecase/notify_contract_test.go` drives a real
  `HandlePaymentSucceeded` flow and captures the two `notify.user` payloads
  billing actually publishes, checked against `kafka/*.json`.

- **compono-telegram-shop** (`tests/test_contract.py`): loads each fixture,
  parses it through the actual Pydantic model in
  `src/infrastructure/billing/models.py`, and asserts every field the model
  declares round-trips to the exact value the fixture provides (not a
  silently-applied default). It runs as a normal pytest file, so it rides the
  existing `lint-and-test` job in `.github/workflows/build-and-push.yml`,
  which already gates `generate-tag`/`build` via `needs: lint-and-test` — no
  workflow changes needed.

## Updating the contract

If billing's serialization changes on purpose (new field, rename, whatever):
1. Update the fixture(s) under `http/` or `kafka/` here.
2. Update billing's contract test if a new type needs pinning.
3. Copy the same fixture changes into the mirror copy in the other repo, and
   update/extend `tests/test_contract.py` there, in the same logical change
   (separate PRs are fine since they're separate repos — just don't let them
   drift apart the way the rest of this contract did).

Bump the version directory (`v2/`, keeping `v1/` until the old shape is fully
retired) for a breaking change instead of editing `v1/` in place, if both
sides can't land atomically.

## Known gaps found while pinning this (BDT-405) — not fixed here

This pass is contract-pinning only (tests/fixtures/CI); it deliberately does
**not** change any production code. Two things were found that are worth
flagging separately:

1. **Live bug: referral stats always report 0.** `GET /referral/{id}/stats`
   (and the unused `GET /referral/{id}`) return `port.ReferralInfo`
   (`internal/port/usecase.go`), which has no json tags and serializes as
   `{"Referrals": [...], "Rewards": [...], "Code": "..."}` — see
   `http/referral_info.json`. But `compono-telegram-shop`'s
   `src/services/referral.py` (`get_referral_count`, `get_reward_count`,
   `get_total_rewards_amount`, ~line 194-207) reads `info.get("referral_count",
   0)`, `info.get("reward_count", 0)`, `info.get("total_rewards_amount", 0)` —
   keys that do not exist anywhere in that response. Those three methods
   **always** return `0`. They feed the bot's "Invite friends" screen
   (`src/bot/routers/menu/getters.py:174-175`, `invite_getter`) — a real user
   in prod always sees 0 referrals / 0 rewards regardless of actual data. This
   predates BDT-405 and is not fixed by it; filed back on the Linear issue.

2. **Minor/dead code, not a live bug:** `BillingReferralInfo`
   (`models.py`) and `BillingClient.get_transaction_stats` /
   `get_referral_info` (`client.py`) are defined but never called anywhere in
   the shop codebase, and would also mis-parse their target responses if they
   were ever wired up (`get_transaction_stats` hits `/transactions/stats`,
   which is the `ListAllTransactions` array endpoint, not a stats dict, so it
   would always return `{}`). Left as-is (dead code cleanup is out of scope
   here); worth a follow-up if anyone wires them up.
