from types import SimpleNamespace

from src.bot.proxy_view import legacy_proxy_plan_id


def _user(plan_id: int, active: bool = True, trial: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        current_subscription=SimpleNamespace(
            is_active=active, is_trial=trial, plan=SimpleNamespace(id=plan_id)
        )
    )


def test_ultra_subscribers_get_the_paid_proxy():
    assert legacy_proxy_plan_id(_user(38)) == 38


def test_existing_paid_plans_still_get_it():
    assert [legacy_proxy_plan_id(_user(p)) for p in (1, 2, 3)] == [1, 2, 3]


def test_trial_and_inactive_do_not():
    assert legacy_proxy_plan_id(_user(38, trial=True)) == 0
    assert legacy_proxy_plan_id(_user(38, active=False)) == 0
