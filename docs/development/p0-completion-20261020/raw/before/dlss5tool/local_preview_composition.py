"""Asynchronous appearance composition for paused image / NR-only previews."""
import json

import cv2

from dlss5tool import appearance
from dlss5tool.i18n import tr
from dlss5tool.preview_jobs import LatestPreviewJob
from dlss5tool.render_cache import file_identity


class LocalPreviewComposition:
    def _invalidate_local_composition(self, *, keep_last=False, reason='source_or_session', record=True):
        from dlss5tool.parameter_contract import invalidation
        if record:
            self._last_parameter_invalidation = {'reason': reason,
                'layers': list(invalidation(reason)) if reason in appearance.GROUPS else ['source', 'nr', 'composition', 'fg']}
        job = getattr(self, '_local_composition_job', None)
        if job:
            job.invalidate(release=reason not in appearance.GROUPS)
        self._cancel_after('_local_composition_after')
        self._local_composition_request = None
        self._local_composition_inputs = None
        self._local_composition_busy = False
        if not keep_last:
            self._local_composition_last = None

    def _local_compose_preview(self, frame, original, processed, settings):
        if processed is None:
            return None
        position = (file_identity(self.video), int(frame))
        mix = float(settings.get('output_mix', 1)) if not settings.get('output_view', 0) else 1.
        if mix == 1 and not appearance.active(settings):
            self._invalidate_local_composition(record=False)
            self._dlss_pending = False
            self._local_composition_last = (position, processed)
            from dlss5tool.preview_feedback import PreviewFeedback
            PreviewFeedback._set_parameter_status(self, 'applied')
            return processed
        look = appearance.settings(settings)
        # Appearance validation intentionally excludes execution settings. Keep
        # the GPU contract separately, including NR's actual automatic choice.
        look['render_gpu'] = settings.get('render_gpu', 'auto')
        adapter = getattr(getattr(self, '_live', None), 'adapter_info', {})
        if 'luid_high' in adapter and 'luid_low' in adapter:
            look['_composition_adapter'] = dict(adapter)
        key = (position, id(original), id(processed), mix, json.dumps(look, sort_keys=True))
        # Retain the identity-bearing inputs until the next request. No frame
        # copies here, and no id reuse can accidentally hit the previous result.
        self._local_composition_inputs = original, processed
        cached = getattr(self, '_last_super_resolution_preview', None)
        source = (cached[1] if cached is not None and cached[0] == frame
                  and cached[1].shape[:2] == processed.shape[:2] else original)
        def compose():
            from dlss5tool.gui import compose_preview_frame
            base = source
            if base.shape[:2] != processed.shape[:2]:
                base = cv2.resize(base, (processed.shape[1], processed.shape[0]), interpolation=cv2.INTER_LANCZOS4)
            return compose_preview_frame(base, processed, output_mix=mix, settings=look)
        job = getattr(self, '_local_composition_job', None)
        if job is None:
            from dlss5tool.residual_composition import release_native_composer
            job = self._local_composition_job = LatestPreviewJob(
                'preview-appearance', persistent=True, cleanup=release_native_composer)
        self._local_composition_request = key
        last = getattr(self, '_local_composition_last', None)
        previous = last[1] if last is not None and last[0] == position else original
        try:
            result = job.request(key, compose)
        except Exception as error:
            self._local_composition_busy = False
            self._dlss_pending = False
            self._clear_preview_wait()
            from dlss5tool.preview_feedback import PreviewFeedback
            PreviewFeedback._set_parameter_status(self, 'failed')
            self.set_status(tr('status.shared_failed', error=str(error).splitlines()[0]))
            if getattr(self, '_local_composition_error', None) != key:
                self.logln('[预览] ' + str(error))
                self._local_composition_error = key
            return previous
        self._local_composition_busy = result is None
        if result is not None:
            self._dlss_pending = False
            self._clear_preview_wait()
            from dlss5tool.preview_feedback import PreviewFeedback
            PreviewFeedback._set_parameter_status(self, 'applied')
            self._local_composition_last = (position, result)
            return result
        self._dlss_pending = True
        self._show_preview_wait(tr('status.shared_updating'))
        if getattr(self, '_local_composition_after', None) is None:
            self._local_composition_after = self.root.after(20, self._poll_local_composition)
        return previous

    def _poll_local_composition(self):
        self._local_composition_after = None
        request = getattr(self, '_local_composition_request', None)
        if request is None:
            return
        if (getattr(self, '_exporting', False) or getattr(self, '_queue_running', False)
                or getattr(self, '_shared_closing', False) or getattr(self, '_clear_preview_pending', False)
                or getattr(self, '_workbench_mode', 'local') != 'local' or self.playing
                or self._uses_shared_render() or not self.video
                or request[0] != (file_identity(self.video), int(self._frame))):
            self._invalidate_local_composition()
            return
        if self._local_composition_job.ready():
            self._split_dlss = None
            self.display_view(quality='full')  # Current settings are checked again before painting.
        else:
            self._local_composition_after = self.root.after(20, self._poll_local_composition)
