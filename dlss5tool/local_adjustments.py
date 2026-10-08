"""Local-media adapter for the same parameter rows as realtime editing."""
from copy import deepcopy
import tkinter as tk
from tkinter import ttk

from dlss5tool import app_settings
from dlss5tool.i18n import tr
from dlss5tool.realtime_controls import ParameterRow
from dlss5tool.ui_widgets import ChromeButton


# Common fields come first; composition is separate and never cross-copied.
FIELDS = (
    ('intensity', 'strength', 'v_intensity', 'v_use_intensity', 'w_intensity'),
    ('local_tone', 'local_tone', 'v_local_tone', 'v_use_local_tone', 'w_local_tone'),
    ('local_struct', 'local_structure', 'v_local_struct', 'v_use_local_struct', 'w_local_struct'),
    ('skin_struct', 'skin_mask', 'v_skin_struct', 'v_auto_mask', 'w_skin_struct'),
    ('output_mix', 'output_mix', 'v_outmix', 'v_use_output_mix', 'w_outmix'),
)


class LocalAdjustments(ttk.Frame):
    def __init__(self, parent, settings, *, ui, styles, on_model, on_output, on_copy):
        super().__init__(parent, style='Panel.TFrame')
        self.settings = settings
        self.styles = dict(styles)
        self._callbacks = on_model, on_output
        self.rows, self._bindings, self._traces = {}, {}, []
        self._building = True
        self._syncing = False
        self._undo = None
        self._pending = None
        self._composition_enabled = True
        self._ui = dict(ui)
        style = tk.StringVar(self, value=str(self.styles.get(settings['v_style'].get(), 0)))
        desc = dict(name='style', label=tr('label.style'), default=app_settings.DEFAULTS['style'],
                    min=0, max=2, step=1, integer=True, choices=[(n, text) for text, n in styles.items()])
        self._add_row('style', desc, style, settings['v_style'], None, tr('parameter.hint.style'))
        for name, label, value_key, switch_key, widget_key in FIELDS:
            if name == 'output_mix':
                ttk.Label(self, text=tr('parameter.composition'), style='Kicker.TLabel').pack(fill='x', pady=(8, 3))
            variable = tk.StringVar(self, value=str(settings[value_key].get()))
            enabled = tk.BooleanVar(self, value=settings[switch_key].get())
            desc = dict(name=name, label=tr('label.' + label), default=app_settings.DEFAULTS[name],
                        min=0, max=5, step=.01, integer=False)
            hint = tr('tooltip.' + label) + '\n' + tr('parameter.switch_hint')
            row = self._add_row(name, desc, variable, settings[value_key],
                                (enabled, settings[switch_key], app_settings.DEFAULTS[switch_key[2:].replace('outmix', 'output_mix')]
                                 if switch_key != 'v_auto_mask' else app_settings.DEFAULTS['use_auto_mask']), hint)
            settings[widget_key], settings[widget_key + '_value'] = row.slider, row.field
            if name == 'output_mix':
                settings['w_use_output_mix'] = row.enable_toggle
        actions = ttk.Frame(self, style='Panel.TFrame')
        actions.pack(fill='x', pady=(2, 4))
        self.reset_button = ChromeButton(actions, text=tr('realtime.editor.reset_group'), variant='tool', ui=ui,
                                         command=lambda: self.reset(tuple(self.rows)))
        self.reset_button.pack(side='right')
        self.undo_button = ChromeButton(actions, text=tr('realtime.editor.undo'), variant='tool', ui=ui,
                                        command=self.undo)
        self.undo_button.pack(side='left')
        self.copy_button = ChromeButton(self, text=tr('parameter.copy_from_realtime'), variant='tool', ui=ui,
                                        command=on_copy)
        self.copy_button.pack(anchor='w', pady=(0, 4))
        self.summary = ttk.Label(self, style='Hint.TLabel', wraplength=300, justify='left')
        self.summary.pack(fill='x')
        self._building = False
        self._snapshot = self.snapshot()
        self.set_limit(5 if settings['v_enable_5x'].get() else 1)

    def _add_row(self, name, desc, raw, actual, switch, hint):
        if switch:
            enabled, actual_enabled, default_enabled = switch
        else:
            enabled = actual_enabled = default_enabled = None
        self._bindings[name] = (actual, actual_enabled, default_enabled)
        row = ParameterRow(self, desc, raw, ui=self._ui, chips=name == 'style',
                           enabled_variable=enabled, allow_percent=name != 'style', hint=hint, range_hint=name != 'style',
                           on_change=self.changed, on_commit=lambda n=name: self.commit(n),
                           on_reset=lambda n=name: self.reset((n,)))
        row.pack(fill='x', pady=(4, 8))
        self.rows[name] = row
        self._traces.append((actual, actual.trace_add('write', lambda *_, n=name: self.sync(n))))
        if actual_enabled is not None:
            self._traces.append((actual_enabled, actual_enabled.trace_add('write', lambda *_, n=name: self.sync(n))))
        return row

    def snapshot(self):
        return {name: (row.variable.get(), row.enabled_variable.get() if row.enabled_variable is not None else None)
                for name, row in self.rows.items()}

    def changed(self):
        if self._building or self._syncing:
            return
        current = self.snapshot()
        if current != self._snapshot and self._pending is None:
            self._pending = deepcopy(self._snapshot)
        self.refresh()

    def sync(self, name):
        if self._building or self._syncing:
            return
        row = self.rows[name]
        actual, actual_enabled, _ = self._bindings[name]
        self._syncing = True
        try:
            row.variable.set(str(self.styles.get(actual.get(), 0) if name == 'style' else actual.get()))
            if actual_enabled is not None:
                row.enabled_variable.set(actual_enabled.get())
        finally:
            self._syncing = False
        self.changed()

    def _apply(self, name, value):
        row = self.rows[name]
        actual, actual_enabled, _ = self._bindings[name]
        self._syncing = True
        try:
            actual.set(next(text for text, n in self.styles.items() if n == value) if name == 'style' else value)
            if actual_enabled is not None:
                actual_enabled.set(bool(row.enabled_variable.get()))
            row.variable.set(str(value))
        finally:
            self._syncing = False

    def commit(self, name=None, *, notify=True):
        names = (name,) if name else tuple(self.rows)
        try:
            values = {n: self.rows[n].value() for n in names}
        except (ValueError, tk.TclError):
            self.refresh()
            return False
        for n, value in values.items():
            self._apply(n, value)
        current = self.snapshot()
        changed = current != self._snapshot
        if changed:
            self._undo = self._pending or self._snapshot
            self._pending = None
            self._snapshot = current
        self.refresh()
        if notify and changed:
            self._callbacks[1 if name == 'output_mix' else 0]()
        return True

    def restore(self, snapshot, *, preserve_undo=False):
        before = self.snapshot()
        changed_names = [name for name in snapshot if snapshot[name] != before[name]]
        from dlss5tool.parameter_values import parse_number
        for name, (raw, _) in snapshot.items():
            try:
                if name != 'style' and 1 < parse_number(raw, percent=True) <= 5:
                    self.settings['v_enable_5x'].set(True)
                    self.set_limit(5)
                    break
            except (ValueError, TypeError):
                pass
        self._syncing = True
        try:
            for name, (raw, enabled) in snapshot.items():
                self.rows[name].variable.set(raw)
                if enabled is not None:
                    self.rows[name].enabled_variable.set(enabled)
        finally:
            self._syncing = False
        self._pending = None
        self._snapshot = self.snapshot()
        # Invalid undo restores the draft without sending it to the renderer.
        valid = self.commit(notify=False)
        self._undo = before if preserve_undo else None
        self.refresh()
        if valid and changed_names:
            self._callbacks[1 if set(changed_names) == {'output_mix'} else 0]()

    def reset(self, names):
        snapshot = self.snapshot()
        for name in names:
            snapshot[name] = (str(self.rows[name].descriptor['default']), self._bindings[name][2])
        self.restore(snapshot, preserve_undo=True)

    def undo(self):
        snapshot = self._pending or self._undo
        if snapshot is not None:
            self.restore(snapshot)

    def replace_common(self, values):
        snapshot = self.snapshot()
        for name, pair in values.items():
            snapshot[name] = pair
        self.restore(snapshot, preserve_undo=True)

    def valid(self):
        try:
            for row in self.rows.values():
                row.value()
            return True
        except (ValueError, tk.TclError):
            return False

    def refresh(self):
        if self._building:
            return
        count = 0
        valid = True
        for name, row in self.rows.items():
            try:
                value = row.value()
                custom = value != row.descriptor['default']
                error = ''
            except (ValueError, tk.TclError) as exc:
                custom, valid, error = True, False, str(exc)
            default_enabled = self._bindings[name][2]
            custom |= row.enabled_variable is not None and row.enabled_variable.get() != default_enabled
            count += int(custom)
            reason = tr('parameter.composition_requires_processed') if name == 'output_mix' and not self._composition_enabled else ''
            row.set_feedback(nondefault=custom, error=error, reason=reason)
        self.summary.configure(text=tr('parameter.local_invalid') if not valid else tr('parameter.custom_count', count=count))
        self.undo_button.configure(state='normal' if self._undo is not None or self._pending is not None else 'disabled')
        self.reset_button.configure(state='normal' if count else 'disabled')

    def set_limit(self, maximum):
        for name, row in self.rows.items():
            if name != 'style':
                row.set_maximum(maximum)
        self.refresh()

    def set_composition_enabled(self, enabled):
        self._composition_enabled = enabled
        self.refresh()

    def apply_theme(self, ui):
        self._ui = dict(ui)
        for row in self.rows.values():
            row.apply_theme(ui)
        for button in (self.reset_button, self.undo_button, self.copy_button):
            button.apply_theme(ui)

    def destroy(self):
        for var, trace in self._traces:
            var.trace_remove('write', trace)
        self._traces.clear()
        super().destroy()
