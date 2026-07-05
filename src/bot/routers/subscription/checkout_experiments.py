from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from aiogram_dialog import DialogManager

from src.models.dto import UserDto
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


def _extract_price_override(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None

    for key in ("price_override", "final_amount", "price", "amount"):
        raw = payload.get(key)
        if raw is None:
            continue
        try:
            return str(Decimal(str(raw)))
        except (InvalidOperation, TypeError, ValueError):
            continue
    return None


def build_checkout_context(
    experiment_service: ExperimentService | None,
    user: UserDto,
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
        if evaluation.payload is not None:
            pricing_experiment = evaluation
            break
    return CheckoutExperimentContext(
        checkout_flow=checkout_flow,
        pricing_experiment=pricing_experiment,
    )


async def track_checkout_event(
    dialog_manager: DialogManager,
    experiment_service: ExperimentService | None,
    user: UserDto,
    event: str,
    *,
    plan_id: int | None = None,
    duration_days: int | None = None,
    gateway_type: str | None = None,
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
    await experiment_service.expose(
        ExperimentFeature.CHECKOUT_FLOW.value,
        user.telegram_id,
        user.created_at,
    )
    experiment_service.record_conversion(
        ExperimentFeature.CHECKOUT_FLOW.value,
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

    await experiment_service.expose(
        ExperimentFeature.CHECKOUT_FLOW.value,
        user.telegram_id,
        user.created_at,
    )
    experiment_service.record_conversion(
        ExperimentFeature.CHECKOUT_FLOW.value,
        user.telegram_id,
        event,
        user.created_at,
    )
