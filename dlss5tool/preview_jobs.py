"""Bounded latest-only CPU preview work. Never calls Tk or waits for rendering."""
import threading


class LatestPreviewJob:
    """One active computation, one replaceable request, one current result.

    Inputs must be immutable snapshots. A changed key invalidates the previous
    result immediately; retired work can finish but cannot publish into a new
    request, including an A -> B -> A transition.
    """
    def __init__(self, name='preview-compose'):
        self.name = name
        self._lock = threading.Lock()
        self._key = self._token = self._pending = self._result = None
        self._thread = None

    def request(self, key, compute):
        with self._lock:
            if key != self._key:
                self._key, self._token = key, object()
                self._result = None
                self._pending = (self._token, compute)
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
                    self._thread.start()
            result = self._result
        if result is None:
            return None
        value, error = result
        if error is not None:
            raise error
        return value

    def ready(self):
        with self._lock:
            return self._result is not None

    def invalidate(self):
        with self._lock:
            self._key = self._token = self._pending = self._result = None

    def _run(self):
        while True:
            with self._lock:
                request, self._pending = self._pending, None
                if request is None:
                    self._thread = None
                    return
            token, compute = request
            try:
                result = (compute(), None)
            except Exception as error:
                result = (None, error)
            with self._lock:
                if token is self._token:
                    self._result = result
            # Do not retain old full-resolution inputs while waiting for work.
            request = compute = result = None
