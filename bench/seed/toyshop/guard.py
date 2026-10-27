"""Safety check: orders above the unattended limit need a named approver."""

from __future__ import annotations

MAX_UNATTENDED_TOTAL = 500.0


def unattended_limit() -> float:
    return MAX_UNATTENDED_TOTAL


def can_auto_submit(total: float, approved_by: str | None = None) -> bool:
    if approved_by:
        return True
    return total <= unattended_limit()
