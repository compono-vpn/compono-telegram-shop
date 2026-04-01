# Phase 4: Remove Duplicate Business Logic from Shop

## Prerequisites

- [ ] Phase 3 deployed: API owns compono_users table
- [ ] Data migration script run: billing users seeded to API
- [ ] Billing USER_SOURCE=api verified in staging
- [ ] Phase 2 live: shop calls API, not billing directly

## Services to Remove

### 1. PaymentGatewayService → BillingClient

**Current:** `src/services/payment_gateway.py` — reads gateway configs from local DB, creates transactions locally.

**Target:** Remove. Use `BillingClient.create_payment()` and `BillingClient.list_gateways()` directly.

**Methods to migrate:**
- `get()` → `billing.get_gateway()`
- `get_by_type()` → `billing.get_gateway_by_type()`
- `get_all()` → `billing.list_gateways()`
- `filter_active()` → `billing.list_active_gateways()`
- `create_payment()` → `billing.create_payment()` (already the primary path)
- `create_test_payment()` → `billing.create_test_payment()`
- `handle_payment_succeeded()` → Remove (billing handles via webhooks now)
- `handle_payment_canceled()` → Remove (billing handles via webhooks now)
- `update()` → `billing.update_gateway()`
- `move_gateway_up()` → `billing.move_gateway_up()`

### 2. SubscriptionService → BillingClient (keep read-only)

**Current:** `src/services/subscription.py` — CRUD on subscriptions table.

**Target:** Read-only via billing API. Creation/updates happen in billing.

**Methods to migrate:**
- `get_current()` → `billing.get_current_subscription()`
- `has_used_trial()` → `billing.has_used_trial()`
- `get()` → Keep Redis cache, fetch from billing on miss
- Remove: `create()`, `update()`, `get_all()`

### 3. TransactionService → BillingClient

**Current:** `src/services/transaction.py` — CRUD on transactions table.

**Target:** Remove. All transaction management is in billing.

**Methods to migrate:**
- `get()` → `billing.get_transaction()`
- `get_by_user()` → `billing.list_transactions()`
- Remove: `create()`, `update()`, `transition_status()`, `count()`, `count_by_status()`

### 4. PricingService → BillingClient

**Current:** `src/services/pricing.py` — pure calculation.

**Target:** Use `billing.calculate_price()` instead.

**Methods to migrate:**
- `calculate()` → `billing.calculate_price()`

## Local Tables to Remove (after migration)

- `transactions` — billing owns this
- `payment_gateways` — billing owns this
- `subscriptions` — billing owns this
- `web_orders` — billing owns this

## What Shop Keeps

- Telegram bot UI (aiogram dialogs, handlers, widgets)
- Web storefront endpoints (`/api/v1/web/*`) — call billing API
- Redis caching layer
- Taskiq for async bot tasks
- `ReferralService` (read-only, display only)
- `PromocodeService` (validation calls billing)
- `UserService` (identity calls API once Phase 3 is live)

## Migration Order

1. PricingService (simplest, pure calculation → single API call)
2. TransactionService (read-only display, billing handles writes)
3. SubscriptionService (keep read-only, remove writes)
4. PaymentGatewayService (most complex, has webhook handling)
5. Drop local tables (after verification period)
