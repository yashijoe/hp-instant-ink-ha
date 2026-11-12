"""Accounting for an HP Instant Ink plan.

Pure Python, no Home Assistant imports, so it can be unit tested on its own.

The printer only exposes a lifetime page counter. The ledger turns that counter
into billing-period figures: pages printed in the period, plan pages left,
rollover (accumulated) pages, overage, and a history of closed periods.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date
from typing import Any

HISTORY_LIMIT = 60


@dataclass(frozen=True)
class PlanConfig:
    """What the user's Instant Ink plan allows."""

    plan_pages: int
    rollover_max: int
    billing_day: int
    overage_block_size: int = 10
    overage_block_price: float = 1.5
    carry_overage_leftover: bool = False


@dataclass(frozen=True)
class PeriodStatus:
    """Figures for the billing period in progress."""

    period_start: date
    next_renewal: date
    days_remaining: int
    printed: int
    plan_pages: int
    plan_remaining: int
    rollover_start: int
    rollover_used: int
    rollover_remaining: int
    free_remaining: int
    overage_pages: int
    overage_blocks: int
    overage_cost: float
    overage_leftover: int
    rollover_projected: int


def _clamped(year: int, month: int, day: int) -> date:
    """Return the given day of the month, or the month's last day if shorter."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def period_start_for(today: date, billing_day: int) -> date:
    """Return the start of the billing period that contains `today`."""
    this_month = _clamped(today.year, today.month, billing_day)
    if today >= this_month:
        return this_month
    year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return _clamped(year, month, billing_day)


def next_renewal(period_start: date, billing_day: int) -> date:
    """Return the renewal date that ends the period starting on `period_start`."""
    year, month = (
        (period_start.year + 1, 1)
        if period_start.month == 12
        else (period_start.year, period_start.month + 1)
    )
    return _clamped(year, month, billing_day)


class Ledger:
    """Tracks one printer's plan usage across billing periods."""

    def __init__(self, config: PlanConfig, state: dict[str, Any] | None = None) -> None:
        self.config = config
        state = state or {}
        raw_start = state.get("period_start")
        self.period_start: date | None = date.fromisoformat(raw_start) if raw_start else None
        self.start_count: int = int(state.get("start_count", 0))
        self.rollover: int = int(state.get("rollover", 0))
        self.last_total: int | None = state.get("last_total")
        self.history: list[dict[str, Any]] = list(state.get("history", []))
        self._initial_printed = 0
        self._initial_rollover = 0

    @property
    def initialised(self) -> bool:
        """Return True once the first period has been opened."""
        return self.period_start is not None

    def set_initial(self, printed_this_period: int, rollover: int) -> None:
        """Set the figures to start from when the first reading arrives."""
        self._initial_printed = max(0, int(printed_this_period))
        self._initial_rollover = max(0, int(rollover))

    def as_dict(self) -> dict[str, Any]:
        """Return the state to persist."""
        return {
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "start_count": self.start_count,
            "rollover": self.rollover,
            "last_total": self.last_total,
            "history": self.history,
        }

    def update(self, today: date, total: int | None) -> bool:
        """Feed a new counter reading (or None if the printer is unreachable).

        Returns True if the persisted state changed.
        """
        before = self.as_dict()

        if total is not None:
            if self.last_total is not None and total < self.last_total:
                # The counter went backwards (printer replaced or reset):
                # keep the pages already counted in this period.
                self.start_count = total - (self.last_total - self.start_count)
            self.last_total = total

        if self.last_total is None:
            return False

        if self.period_start is None:
            self.period_start = period_start_for(today, self.config.billing_day)
            self.start_count = self.last_total - self._initial_printed
            self.rollover = min(self._initial_rollover, self.config.rollover_max)

        while today >= (renewal := next_renewal(self.period_start, self.config.billing_day)):
            self._close_period(renewal)

        return self.as_dict() != before

    def adjust(
        self,
        *,
        printed: int | None = None,
        rollover: int | None = None,
        period_start: date | None = None,
    ) -> None:
        """Correct the current period so it matches the HP account."""
        if not self.initialised or self.last_total is None:
            raise ValueError("No reading from the printer yet")
        if period_start is not None:
            self.period_start = period_start
        if printed is not None:
            self.start_count = self.last_total - max(0, int(printed))
        if rollover is not None:
            self.rollover = max(0, int(rollover))

    def status(self, today: date) -> PeriodStatus:
        """Return the figures for the period in progress."""
        if self.period_start is None or self.last_total is None:
            raise ValueError("No reading from the printer yet")
        cfg = self.config
        printed = max(0, self.last_total - self.start_count)
        plan_remaining = max(0, cfg.plan_pages - printed)
        beyond_plan = max(0, printed - cfg.plan_pages)
        rollover_used = min(beyond_plan, self.rollover)
        rollover_remaining = self.rollover - rollover_used
        overage_pages = beyond_plan - rollover_used
        block = max(1, cfg.overage_block_size)
        overage_blocks = math.ceil(overage_pages / block)
        overage_leftover = overage_blocks * block - overage_pages
        carried = plan_remaining + rollover_remaining
        if cfg.carry_overage_leftover:
            carried += overage_leftover
        renewal = next_renewal(self.period_start, cfg.billing_day)
        return PeriodStatus(
            period_start=self.period_start,
            next_renewal=renewal,
            days_remaining=max(0, (renewal - today).days),
            printed=printed,
            plan_pages=cfg.plan_pages,
            plan_remaining=plan_remaining,
            rollover_start=self.rollover,
            rollover_used=rollover_used,
            rollover_remaining=rollover_remaining,
            free_remaining=plan_remaining + rollover_remaining,
            overage_pages=overage_pages,
            overage_blocks=overage_blocks,
            overage_cost=round(overage_blocks * cfg.overage_block_price, 2),
            overage_leftover=overage_leftover,
            rollover_projected=min(cfg.rollover_max, carried),
        )

    def _close_period(self, renewal: date) -> None:
        """Archive the period in progress and open the next one."""
        status = self.status(renewal)
        self.history.append(
            {
                "start": status.period_start.isoformat(),
                "end": renewal.isoformat(),
                "printed": status.printed,
                "plan_pages": status.plan_pages,
                "rollover_start": status.rollover_start,
                "rollover_used": status.rollover_used,
                "rollover_end": status.rollover_projected,
                "accumulated": status.rollover_projected - status.rollover_start,
                "overage_pages": status.overage_pages,
                "overage_cost": status.overage_cost,
            }
        )
        del self.history[:-HISTORY_LIMIT]
        self.period_start = renewal
        self.start_count = self.last_total or 0
        self.rollover = status.rollover_projected
