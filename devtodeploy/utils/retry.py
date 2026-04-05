from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

F = TypeVar("F", bound=Callable[..., Any])


def with_retry(
    max_attempts: int = 4,
    min_wait: float = 2.0,
    max_wait: float = 16.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """Exponential-backoff retry decorator (2s → 4s → 8s → 16s)."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            retrying = retry(
                retry=retry_if_exception_type(exceptions),
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
                reraise=True,
            )
            return retrying(func)(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


__all__ = ["with_retry", "RetryError"]
