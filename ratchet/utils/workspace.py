"""Create and clean up isolated working directories."""
import shutil
import tempfile
import weakref


class Workspace:
    """Manage a directory that is removed when closed or collected."""
    def __init__(self, prefix=None):
        self.name = tempfile.mkdtemp(prefix=prefix)
        self._finalizer = weakref.finalize(self, shutil.rmtree, self.name, ignore_errors=True)

    def cleanup(self):
        self._finalizer()

    def __enter__(self):
        return self.name

    def __exit__(self, exc_type, exc, traceback):
        self.cleanup()
