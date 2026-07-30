from datetime import timedelta

from kajovodagmar.security.rate_limit import evaluate_login_attempt, restriction_until
from kajovodagmar.types import utc_now


def test_initial_failed_attempt_remains_retryable() -> None:
    decision = evaluate_login_attempt(0)
    assert decision.allowed
    assert decision.next_failed_count == 1


def test_repeated_attempts_trigger_progressive_delay() -> None:
    fifth = evaluate_login_attempt(4)
    eighth = evaluate_login_attempt(7)
    assert not fifth.allowed
    assert not eighth.allowed
    assert eighth.retry_after_seconds > fifth.retry_after_seconds
    assert eighth.retry_after_seconds <= 3600


def test_existing_restriction_and_expired_restriction_are_distinguished() -> None:
    restricted = evaluate_login_attempt(
        2, (utc_now() + timedelta(seconds=30)).isoformat()
    )
    expired = evaluate_login_attempt(2, (utc_now() - timedelta(seconds=1)).isoformat())
    assert not restricted.allowed
    assert restricted.next_failed_count == 2
    assert expired.allowed
    assert expired.next_failed_count == 3


def test_restriction_deadline_starts_at_fifth_failure() -> None:
    assert restriction_until(4) is None
    deadline = restriction_until(5)
    assert deadline is not None
    assert deadline > utc_now()
