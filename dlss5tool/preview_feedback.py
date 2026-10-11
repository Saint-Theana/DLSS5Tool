"""Main-thread-only preview wait feedback in the bottom status bar."""
import time
from tkinter import TclError

from dlss5tool.i18n import tr


class PreviewFeedback:
    def _set_parameter_status(self, state):
        editor = getattr(self, '_local_adjustments', None)
        if editor is not None:
            meta = getattr(self, '_video_color_info', None) or {}
            config = self._preview_effect_settings() if hasattr(self, '_preview_effect_settings') else {}
            editor.set_operation_state(state, hdr=bool(meta.get('is_hdr') and config.get('hdr_mode')))

    def _show_preview_wait(self, stage, key=None):
        PreviewFeedback._set_parameter_status(self, 'pending')
        if key is None:
            key = (getattr(self, 'video', None), getattr(self, '_frame', 0))
        if getattr(self, '_preview_wait_key', None) != key:
            self._preview_wait_key = key
            self._preview_wait_started = time.monotonic()
        self._preview_wait_stage = ' · '.join(stage.splitlines())
        self._paint_preview_wait()
        if getattr(self, '_preview_wait_after', None) is None:
            self._preview_wait_after = self.root.after(200, self._tick_preview_wait)

    def _paint_preview_wait(self):
        elapsed = max(0., time.monotonic() - self._preview_wait_started)
        pulse = '·' * (1 + int(elapsed * 5) % 3)
        text = tr('status.preview_wait', stage=self._preview_wait_stage,
                  seconds=int(elapsed), pulse=pulse)
        self._preview_wait_text = text
        self.set_status(text)

    def _tick_preview_wait(self):
        self._preview_wait_after = None
        if getattr(self, '_preview_wait_key', None) is None:
            return
        if (not getattr(self, 'video', None) or getattr(self, '_exporting', False)
                or getattr(self, '_shared_closing', False)):
            self._clear_preview_wait()
            return
        self._paint_preview_wait()
        self._preview_wait_after = self.root.after(200, self._tick_preview_wait)

    def _clear_preview_wait(self):
        if getattr(self, '_preview_wait_key', None) is not None:
            PreviewFeedback._set_parameter_status(self, 'idle')
        if getattr(self, '_preview_wait_after', None) is not None:
            self._cancel_after('_preview_wait_after')
        if getattr(self, '_preview_wait_key', None) is not None:
            self._preview_wait_key = None
            # Clear only our own message; never erase a newer error/export status.
            label = getattr(self, 'eta_label', None)
            try:
                if label is not None and label.cget('text') == self._preview_wait_text:
                    self.set_status('')
            except TclError:
                pass  # The window may already be closing.
