"""Bounded latest-only CPU preview work. Never calls Tk or waits for rendering."""
import threading
import time
from dlss5tool.deferred_error import ErrorSnapshot


class LatestPreviewJob:
    """One active computation, one replaceable request, one current result.

    Inputs must be immutable snapshots. A changed key invalidates the previous
    result immediately; retired work can finish but cannot publish into a new
    request, including an A -> B -> A transition.
    """
    def __init__(self, name='preview-compose', *, persistent=False, cleanup=None, idle_seconds=30):
        self.name = name
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._persistent, self._cleanup = persistent, cleanup
        self._idle_seconds = idle_seconds
        self._closed = self._cleanup_pending = False
        self._key = self._token = self._pending = self._result = None
        self._thread = None

    def request(self, key, compute):
        with self._lock:
            if self._closed:
                return None
            if key != self._key:
                self._key, self._token = key, object()
                self._result = None
                self._pending = (self._token, compute)
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
                    self._thread.start()
                self._wake.notify_all()
            result = self._result
        if result is None:
            return None
        value, error = result
        if error is not None:
            raise error.exception() from None
        return value

    def ready(self):
        with self._lock:
            return self._result is not None

    def invalidate(self, *, release=True):
        with self._lock:
            self._key = self._token = self._pending = self._result = None
            self._cleanup_pending |= release
            self._wake.notify_all()

    def close(self):
        """Non-blocking retirement; cleanup happens after any active dispatch."""
        with self._lock:
            self._closed = True
            self._key = self._token = self._pending = self._result = None
            self._wake.notify_all()

    def is_alive(self):
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def _release_resources(self):
        if self._cleanup is not None:
            self._cleanup()

    def _run(self):
        idle_since = time.monotonic()
        released = False
        while True:
            with self._lock:
                while (self._persistent and not self._pending and not self._closed
                       and not self._cleanup_pending):
                    remaining = self._idle_seconds - (time.monotonic() - idle_since)
                    if not released and remaining <= 0:
                        self._cleanup_pending = True
                        break
                    self._wake.wait(None if released else max(0, remaining))
                stop = self._closed or (not self._persistent and self._pending is None)
                cleanup = self._cleanup_pending or stop
                self._cleanup_pending = False
            if cleanup:
                # Never release a device on the UI thread or during compute.
                self._release_resources()
                released = True
            if stop:
                with self._lock:
                    # A request can race a short-lived worker's idle check.
                    if not self._closed and self._pending is not None:
                        continue
                    self._thread = None
                return
            with self._lock:
                request, self._pending = self._pending, None
                if request is None:
                    continue
            token, compute = request
            try:
                result = (compute(), None)
            except Exception as error:
                result = (None, ErrorSnapshot(error))
            with self._lock:
                if token is self._token:
                    self._result = result
            # Do not retain old full-resolution inputs while waiting for work.
            request = compute = result = None
            idle_since = time.monotonic()
            released = False
