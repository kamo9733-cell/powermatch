"""Billing interface only. No payment processing: NoopProvider just records plan state."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Plan:
    name: str
    max_locations: int
    max_cameras: int
    max_retention_days: int


PLANS = {
    "trial": Plan("trial", 1, 4, 7),
    "starter": Plan("starter", 1, 8, 30),
    "pro": Plan("pro", 5, 40, 90),
    "enterprise": Plan("enterprise", 10**6, 10**6, 365),
}


class BillingProvider(Protocol):
    def set_plan(self, org_id: str, plan: str) -> None: ...


class NoopProvider:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def set_plan(self, org_id: str, plan: str) -> None:
        self.calls.append((org_id, plan))
