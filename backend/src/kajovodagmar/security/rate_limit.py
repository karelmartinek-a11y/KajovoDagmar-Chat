from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from kajovodagmar.types import utc_now


@dataclass(frozen=True, slots=True)
class RestrictionDecision:
    allowed: bool
    retry_after_seconds: int
    next_failed_count: int


def evaluate_login_attempt(
    failed_count: int, restricted_until_iso: str | None = None
) -> RestrictionDecision:
    now = utc_now()
    if restricted_until_iso:
        from datetime import datetime

        until = datetime.fromisoformat(restricted_until_iso)
        if until > now:
            return RestrictionDecision(
                False, max(1, int((until - now).total_seconds())), failed_count
            )
    next_count = failed_count + 1
    if next_count < 5:
        return RestrictionDecision(True, 0, next_count)
    delay = min(3600, 30 * (2 ** min(next_count - 5, 7)))
    return RestrictionDecision(False, delay, next_count)


def restriction_until(failed_count: int):
    if failed_count < 5:
        return None
    delay = min(3600, 30 * (2 ** min(failed_count - 5, 7)))
    return utc_now() + timedelta(seconds=delay)
