from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from aiogram_dialog import DialogManager

from src.core.enums import PurchaseType
from src.models.dto import PlanDto, UserDto
from src.services.experiment import ExperimentFeature, ExperimentService, FeatureEvaluation

CHECKOUT_EVENT_CACHE_KEY = "checkout_event_fires"
PRICING_EXPERIMENTS = (
    ExperimentFeature.INTRO_PRICE,
    ExperimentFeature.START_TIER_PRICE,
)


@dataclass(frozen=True)
class CheckoutExperimentContext:
    checkout_flow: FeatureEvaluation
    pricing_experiment: FeatureEvaluation | None

    @property
    def feature_keys(self) -> tuple[str, ...]:
        keys = [self.checkout_flow.feature_key]
        if self.pricing_experiment is not None:
            keys.append(self.pricing_experiment.feature_key)
        return tuple(keys)

    @property
    def billing_experiment(self) -> dict[str, Any] | None:
        if self.pricing_experiment is None:
            return None

        payload = self.pricing_experiment.payload
        experiment: dict[str, Any] = {
            "feature_key": self.pricing_experiment.feature_key,
            "variant_key": self.pricing_experiment.variant,
            "payload": payload,
        }
        price_override = _extract_price_override(payload)
        if price_override is not None:
            experiment["price_override"] = price_override
        return experiment


def _format_amount(raw: Any) -> str | None:
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None

    return format(amount.normalize(), "f")


def _extract_price_override(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    explicit_override = payload.get("price_override")
    if isinstance(explicit_override, dict):
        price = _format_amount(explicit_override.get("price"))
        if price is None:
            return None
        override = {**explicit_override, "price": price}
        return override

    for key in ("price_override", "final_amount", "price", "amount"):
        raw = payload.get(key)
        if raw is None:
            continue
        price = _format_amount(raw)
        if price is not None:
            return {"price": price}
    return None


def build_checkout_context(
    experiment_service: ExperimentService | None,
    user: UserDto,
    *,
    plan: PlanDto | None = None,
    duration_days: int | None = None,
    purchase_type: PurchaseType | str | None = None,
) -> CheckoutExperimentContext | None:
    if experiment_service is None:
        return None

    checkout_flow = experiment_service.evaluate_feature_for_user(
        user,
        ExperimentFeature.CHECKOUT_FLOW,
    )
    pricing_experiment = None
    for feature in PRICING_EXPERIMENTS:
        evaluation = experiment_service.evaluate_feature_for_user(user, feature)
        if evaluation.payload is not None and _is_pricing_experiment_eligible(
            evaluation.feature_key,
            plan=plan,
            duration_days=duration_days,
            purchase_type=purchase_type,
        ):
            pricing_experiment = evaluation
            break
    return CheckoutExperimentContext(
        checkout_flow=checkout_flow,
        pricing_experiment=pricing_experiment,
    )


def _is_pricing_experiment_eligible(
    feature_key: str,
    *,
    plan: PlanDto | None,
    duration_days: int | None,
    purchase_type: PurchaseType | str | None,
) -> bool:
    price_features = {
        ExperimentFeature.INTRO_PRICE.value,
        ExperimentFeature.START_TIER_PRICE.value,
    }
    if feature_key not in price_features:
        return True

    if duration_days != 30:
        return False

    if feature_key == ExperimentFeature.INTRO_PRICE.value:
        return _purchase_type_value(purchase_type) == PurchaseType.NEW.value

    return plan is not None and _is_start_tier_plan(plan)


def _purchase_type_value(purchase_type: PurchaseType | str | None) -> str | None:
    if purchase_type is None:
        return None
    return purchase_type.value if hasattr(purchase_type, "value") else str(purchase_type)


def _is_start_tier_plan(plan: PlanDto) -> bool:
    fields = [plan.name or "", plan.tag or ""]
    if any("start" in value.lower() or "старт" in value.lower() for value in fields):
        return True
    return plan.traffic_limit == 100 and plan.device_limit == 2


async def track_checkout_event(
    dialog_manager: DialogManager,
    experiment_service: ExperimentService | None,
    user: UserDto,
    event: str,
    *,
    plan: PlanDto | None = None,
    plan_id: int | None = None,
    duration_days: int | None = None,
    gateway_type: str | None = None,
    purchase_type: PurchaseType | str | None = None,
) -> None:
    if experiment_service is None:
        return

    cache = dialog_manager.dialog_data.setdefault(CHECKOUT_EVENT_CACHE_KEY, {})
    cache_key = "|".join(
        (
            event,
            str(user.telegram_id),
            str(plan_id or ""),
            str(duration_days or ""),
            gateway_type or "",
        )
    )
    if cache_key in cache:
        return

    cache[cache_key] = True
    context = build_checkout_context(
        experiment_service,
        user,
        plan=plan,
        duration_days=duration_days,
        purchase_type=purchase_type,
    )
    if context is None:
        return

    for feature_key in context.feature_keys:
        await experiment_service.expose(
            feature_key,
            user.telegram_id,
            user.created_at,
        )
        experiment_service.record_conversion(
            feature_key,
            user.telegram_id,
            event,
            user.created_at,
        )


async def track_payment_outcome(
    experiment_service: ExperimentService | None,
    user: UserDto,
    event: str,
) -> None:
    if experiment_service is None:
        return

    context = build_checkout_context(experiment_service, user)
    if context is None:
        return

    for feature_key in context.feature_keys:
        await experiment_service.expose(
            feature_key,
            user.telegram_id,
            user.created_at,
        )
        experiment_service.record_conversion(
            feature_key,
            user.telegram_id,
            event,
            user.created_at,
        )
