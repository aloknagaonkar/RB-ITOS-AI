"""Cross-platform advisory lock for append-only observation journals."""
from __future__ import annotations

import os

if os.name == "nt":
    import msvcrt

    LOCK_SH = 1
    LOCK_EX = 2
    LOCK_UN = 4
    LOCK_NB = 8

    def flock(fd: int, operation: int) -> None:
        position = os.lseek(fd, 0, os.SEEK_CUR)
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            if operation & LOCK_UN:
                mode = msvcrt.LK_UNLCK
            elif operation & LOCK_NB:
                mode = msvcrt.LK_NBLCK
            else:
                mode = msvcrt.LK_LOCK
            # Windows has no shared msvcrt byte-range lock. Reader locks are
            # exclusive, preserving safety at the cost of read concurrency.
            msvcrt.locking(fd, mode, 1)
        finally:
            os.lseek(fd, position, os.SEEK_SET)
else:
    from fcntl import LOCK_EX, LOCK_NB, LOCK_SH, LOCK_UN, flock
