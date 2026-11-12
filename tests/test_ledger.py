"""Tests for the plan accounting (no Home Assistant needed)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[1] / "custom_components" / "hp_instant_ink" / "ledger.py"
_SPEC = importlib.util.spec_from_file_location("hp_ledger", _PATH)
ledger_mod = importlib.util.module_from_spec(_SPEC)
sys.modules["hp_ledger"] = ledger_mod
_SPEC.loader.exec_module(ledger_mod)

Ledger = ledger_mod.Ledger
PlanConfig = ledger_mod.PlanConfig
period_start_for = ledger_mod.period_start_for
next_renewal = ledger_mod.next_renewal

PLAN = PlanConfig(plan_pages=50, rollover_max=150, billing_day=5)


def make(plan=PLAN, *, today=date(2026, 11, 12), total=562, printed=0, rollover=0):
    ledger = Ledger(plan)
    ledger.set_initial(printed, rollover)
    ledger.update(today, total)
    return ledger


def test_period_boundaries():
    assert period_start_for(date(2026, 11, 12), 5) == date(2026, 11, 5)
    assert period_start_for(date(2026, 11, 4), 5) == date(2026, 10, 5)
    assert period_start_for(date(2026, 1, 3), 5) == date(2025, 12, 5)
    assert next_renewal(date(2026, 12, 5), 5) == date(2027, 1, 5)


def test_billing_day_31_is_clamped_to_short_months():
    assert period_start_for(date(2027, 2, 28), 31) == date(2027, 2, 28)
    assert next_renewal(date(2027, 1, 31), 31) == date(2027, 2, 28)
    assert next_renewal(date(2027, 2, 28), 31) == date(2027, 3, 31)


def test_first_reading_uses_initial_figures():
    ledger = make(printed=12, rollover=30)
    status = ledger.status(date(2026, 11, 12))
    assert status.period_start == date(2026, 11, 5)
    assert status.next_renewal == date(2026, 12, 5)
    assert status.days_remaining == 23
    assert status.printed == 12
    assert status.plan_remaining == 38
    assert status.rollover_remaining == 30
    assert status.free_remaining == 68
    assert status.rollover_projected == 68
    assert status.overage_pages == 0


def test_plan_then_rollover_then_overage():
    ledger = make(rollover=20)
    ledger.update(date(2026, 11, 20), 562 + 60)
    status = ledger.status(date(2026, 11, 20))
    assert (status.plan_remaining, status.rollover_used, status.rollover_remaining) == (0, 10, 10)
    assert status.overage_pages == 0

    ledger.update(date(2026, 11, 25), 562 + 83)
    status = ledger.status(date(2026, 11, 25))
    assert status.rollover_remaining == 0
    assert status.overage_pages == 13
    assert status.overage_blocks == 2
    assert status.overage_cost == 3.0
    assert status.overage_leftover == 7
    assert status.rollover_projected == 0


def test_renewal_accumulates_unused_pages_and_records_history():
    ledger = make()
    ledger.update(date(2026, 12, 4), 562 + 20)
    assert ledger.history == []

    assert ledger.update(date(2026, 12, 5), 562 + 20)
    assert ledger.history == [
        {
            "start": "2026-11-05",
            "end": "2026-12-05",
            "printed": 20,
            "plan_pages": 50,
            "rollover_start": 0,
            "rollover_used": 0,
            "rollover_end": 30,
            "accumulated": 30,
            "overage_pages": 0,
            "overage_cost": 0.0,
        }
    ]
    status = ledger.status(date(2026, 12, 5))
    assert status.period_start == date(2026, 12, 5)
    assert status.printed == 0
    assert status.rollover_remaining == 30
    assert status.free_remaining == 80


def test_rollover_is_capped():
    ledger = make(rollover=140)
    ledger.update(date(2026, 12, 5), 562 + 5)
    assert ledger.rollover == 150
    assert ledger.history[-1]["accumulated"] == 10


def test_overage_leftover_only_carried_when_enabled():
    for carry, expected in ((False, 0), (True, 7)):
        plan = PlanConfig(plan_pages=50, rollover_max=150, billing_day=5, carry_overage_leftover=carry)
        ledger = make(plan)
        ledger.update(date(2026, 12, 5), 562 + 63)
        assert ledger.rollover == expected
        assert ledger.history[-1]["overage_pages"] == 13


def test_printer_offline_at_renewal_still_closes_the_period():
    ledger = make()
    ledger.update(date(2026, 11, 30), 562 + 15)
    assert ledger.update(date(2026, 12, 6), None)
    assert ledger.history[-1]["printed"] == 15
    assert ledger.status(date(2026, 12, 6)).printed == 0


def test_catches_up_several_missed_periods():
    ledger = make()
    ledger.update(date(2027, 2, 10), 562 + 40)
    assert [h["start"] for h in ledger.history] == ["2026-11-05", "2026-12-05", "2027-01-05"]
    assert [h["printed"] for h in ledger.history] == [40, 0, 0]
    assert ledger.rollover == 110


def test_counter_reset_keeps_pages_of_the_period():
    ledger = make(printed=12)
    ledger.update(date(2026, 11, 15), 3)
    assert ledger.status(date(2026, 11, 15)).printed == 12
    ledger.update(date(2026, 11, 16), 8)
    assert ledger.status(date(2026, 11, 16)).printed == 17


def test_state_survives_a_restart():
    ledger = make(printed=12, rollover=30)
    ledger.update(date(2026, 12, 5), 600)
    restored = Ledger(PLAN, ledger.as_dict())
    assert restored.as_dict() == ledger.as_dict()
    assert restored.status(date(2026, 12, 6)) == ledger.status(date(2026, 12, 6))
    assert restored.update(date(2026, 12, 6), 600) is False


def test_adjust_aligns_with_the_hp_account():
    ledger = make()
    ledger.adjust(printed=25, rollover=40, period_start=date(2026, 11, 8))
    status = ledger.status(date(2026, 11, 12))
    assert (status.printed, status.rollover_remaining) == (25, 40)
    assert status.period_start == date(2026, 11, 8)


def test_adjust_before_any_reading_is_rejected():
    with pytest.raises(ValueError):
        Ledger(PLAN).adjust(printed=1)
