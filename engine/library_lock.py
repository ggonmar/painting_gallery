"""
Cross-process lock so that only one painting_renamer run reads/writes the library at a time
(e.g. several uploads from the web processed concurrently on the NAS).
On platforms without fcntl (Windows) the lock is a no-op.
"""

from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

LOCK_FILE = Path(__file__).parent / 'jobs' / '.library.lock'


@contextmanager
def library_lock():
    if fcntl is None:
        yield
        return
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, 'w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
