from __future__ import annotations

from contextlib import contextmanager
import fcntl
from pathlib import Path
import time
from typing import Iterator

LOCK_UNAVAILABLE_EXIT_CODE = 75


class LockUnavailableError(RuntimeError):
    """Raised when another corpus operation holds the shared promote lock."""


@contextmanager
def acquire_lock(lock_file: Path | None, *, timeout_seconds: float = 30.0) -> Iterator[None]:
    if lock_file is None:
        yield
        return

    lock_file.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_file.open('a')
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise LockUnavailableError(f'lock unavailable: {lock_file}') from exc
                time.sleep(min(0.1, max(deadline - time.monotonic(), 0.0)))
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


__all__ = ['LOCK_UNAVAILABLE_EXIT_CODE', 'LockUnavailableError', 'acquire_lock']
