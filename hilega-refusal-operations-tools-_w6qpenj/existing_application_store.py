"""Open an existing application DB; never initialize its schema."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import sqlite3
import stat


def regular_private(path):
    path = Path(path).absolute()
    if (not path.is_file() or path.is_symlink()
            or any(p.is_symlink() for p in path.parents)):
        raise ValueError("EXISTING_REGULAR_FILE_REQUIRED")
    value = path.stat()
    if value.st_uid != os.getuid() or stat.S_IMODE(value.st_mode) & 0o077:
        raise ValueError("PRIVATE_OWNED_FILE_REQUIRED")
    return path


class ExistingApplicationStore:
    def __init__(self, path):
        self.path = regular_private(path)

    @contextmanager
    def db(self):
        regular_private(self.path)
        db = sqlite3.connect(
            self.path.as_uri() + "?mode=rw", uri=True, timeout=15)
        try:
            db.execute("PRAGMA synchronous=FULL")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def lock(self):
        path = regular_private(str(self.path) + ".control.lock")
        # Reuse the application's existing lock; never create one here.
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(fd, "a") as stream:
            value = os.fstat(stream.fileno())
            if (not stat.S_ISREG(value.st_mode)
                    or value.st_uid != os.getuid()
                    or stat.S_IMODE(value.st_mode) & 0o077):
                raise ValueError("PRIVATE_OWNED_LOCK_REQUIRED")
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)