"""Local-media adapter for the same parameter rows as realtime editing."""
from copy import deepcopy
import json
import tkinter as tk
from tkinter import messagebox, ttk

from dlss5tool import app_settings, ui_theme, appearance
from dlss5tool.i18n import tr
from dlss5tool.realtime_controls import ParameterRow
from dlss5tool.ui_widgets import ChromeButton, Tooltip


# Legacy mix is separate from the portable appearance groups.
FIELDS = (
    ('intensity', 'strength', 'v_intensity', 'v_use_intensity', 'w_intensity'),
    ('local_tone', 'local_tone', 'v_local_tone', 'v_use_local_tone', 'w_local_tone'),
    ('local_struct', 'local_structure', 'v_local_struct', 'v_use_local_struct', 'w_local_struct'),
    ('skin_struct', 'skin_mask', 'v_skin_struct', 'v_auto_mask', 'w_skin_struct'),
    ('output_mix', 'output_mix', 'v_outmix', 'v_use_output_mix', 'w_outmix'),
)


class LocalAdjustments(ttk.Frame):
    def __init__(self, parent, settings, *, ui, styles, on_model, on_output, on_copy, on_regions=None):
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
        self._on_copy = on_copy
        self._menu = None
        self._region_editor = None
        saved_look = appearance.settings(settings.get('_appearance', {}), strict=False)
        self._regions = deepcopy(saved_look['nr_quality']['regions'])
        self.actions = ttk.Frame(self, style='Panel.TFrame')
        self.actions.pack(fill='x', pady=(4, 8))
        self.more_button = ChromeButton(self.actions, text=tr('realtime.editor.more'), icon='more',
                                        icon_only=True, variant='tool', ui=ui, command=self.show_menu)
        self.more_button.pack(side='right', padx=(4, 0))
        Tooltip(self.more_button, tr('realtime.editor.more'))
        self.undo_button = ChromeButton(self.actions, text=tr('realtime.polish.undo_parameters'), variant='tool', ui=ui,
                                        icon='undo', command=self.undo)
        self.undo_button.pack(side='right')
        Tooltip(self.undo_button, tr('realtime.editor.undo_hint'))
        self.heading = ttk.Label(self.actions, text='DLSS NR', style='TLabel', font=ui_theme.UI_FONT_BOLD)
        self.heading.pack(side='left')
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
        for group, fields in (('nr_residual', appearance.RESIDUAL_FIELDS),
                              ('nr_quality', (*appearance.QUALITY_FIELDS, 'feather', 'protection'))):
            ttk.Label(self, text=tr('appearance.' + group), style='Kicker.TLabel').pack(fill='x', pady=(8, 3))
            for key in fields:
                name = group + '.' + key
                value = saved_look[group][key]
                integer = key == 'protection'
                actual = tk.IntVar(self, value=int(value)) if integer else tk.DoubleVar(self, value=value)
                settings['v_' + name] = actual
                desc = dict(name=name, label=tr('appearance.' + key), default=int(value) if integer else appearance.DEFAULTS[group][key],
                            min=1 if key == 'residualMultiplier' else 0,
                            max=256 if key == 'feather' else 1 if integer else 2,
                            step=1 if key in ('feather', 'protection') else .01, integer=integer)
                if integer:
                    desc.update(default=0, choices=[(0, tr('parameter.off')), (1, tr('parameter.on'))])
                self._add_row(name, desc, tk.StringVar(self, value=str(int(value) if integer else value)), actual,
                              None, tr('appearance.residual_hint' if group == 'nr_residual' else 'appearance.quality_hint'))
        if on_regions:
            button = ChromeButton(self, text=tr('realtime.preview.regions'), ui=ui, variant='tool', command=on_regions)
            button.pack(anchor='w', pady=4)
            self.region_button = button
        self.region_summary = ttk.Label(self, style='Hint.TLabel', wraplength=300)
        self.region_summary.pack(fill='x')
        self.summary = ttk.Label(self, style='Hint.TLabel', wraplength=300, justify='left')
        self._building = False
        self._snapshot = self.snapshot()
        self._applied_snapshot = self._snapshot
        self.set_limit(5 if settings['v_enable_5x'].get() else 1)

    def _add_row(self, name, desc, raw, actual, switch, hint):
        if switch:
            enabled, actual_enabled, default_enabled = switch
        else:
            enabled = actual_enabled = default_enabled = None
        self._bindings[name] = (actual, actual_enabled, default_enabled)
        row = ParameterRow(self, desc, raw, ui=self._ui, chips=name == 'style' or name.endswith('.protection'),
                           enabled_variable=enabled, allow_percent=name != 'style', hint=hint, range_hint=name != 'style',
                           on_change=self.changed, on_commit=lambda n=name: self.commit(n))
        row.pack(fill='x', pady=(4, 8))
        self.rows[name] = row
        self._traces.append((actual, actual.trace_add('write', lambda *_, n=name: self.sync(n))))
        if actual_enabled is not None:
            self._traces.append((actual_enabled, actual_enabled.trace_add('write', lambda *_, n=name: self.sync(n))))
        return row

    def snapshot(self):
        return {**{name: (row.variable.get(), row.enabled_variable.get() if row.enabled_variable is not None else None)
                   for name, row in self.rows.items()}, '_regions': (json.dumps(self._regions), None)}

    def appearance_settings(self):
        values = deepcopy(appearance.DEFAULTS)
        for group, fields in (('nr_residual', appearance.RESIDUAL_FIELDS), ('nr_quality', (*appearance.QUALITY_FIELDS, 'feather', 'protection'))):
            for key in fields:
                value = self._bindings[group + '.' + key][0].get()
                values[group][key] = bool(value) if key == 'protection' else float(value)
        values['nr_quality']['regions'] = deepcopy(self._regions)
        return appearance.settings(values)

    def commit_regions(self, regions):
        appearance.quality({'regions': regions})
        snapshot = self.snapshot()
        snapshot['_regions'] = (json.dumps(regions), None)
        snapshot['nr_quality.protection'] = (str(int(bool(regions))), None)
        self.restore(snapshot, preserve_undo=True)

    @staticmethod
    def output_only(names):
        return all(n == 'output_mix' or n == '_regions' or n.startswith('nr_') for n in names)

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
            target = next(text for text, n in self.styles.items() if n == value) if name == 'style' else value
            if actual.get() != target:
                actual.set(target)
            if actual_enabled is not None:
                enabled = bool(row.enabled_variable.get())
                if actual_enabled.get() != enabled:
                    actual_enabled.set(enabled)
            if row.variable.get() != str(value):
                row.variable.set(str(value))
        finally:
            self._syncing = False

    def commit(self, name=None, *, notify=True):
        # Preview polling / autosave reads must not commit an unfinished drag,
        # consume its undo snapshot, or repeatedly rewrite every Tk variable.
        if not notify and any(row.slider is not None and row.slider._dragging for row in self.rows.values()):
            return False
        if self.snapshot() == self._snapshot == self._applied_snapshot:
            return True
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
        self.settings['_appearance'] = self.appearance_settings()
        self._applied_snapshot = current
        self.refresh()
        if notify and changed:
            self._callbacks[1 if self.output_only(names) else 0]()
        return True

    def restore(self, snapshot, *, preserve_undo=False):
        before = self.snapshot()
        changed_names = [name for name in snapshot if snapshot[name] != before[name]]
        from dlss5tool.parameter_values import parse_number
        for name, (raw, _) in snapshot.items():
            try:
                if name in {f[0] for f in FIELDS} and 1 < parse_number(raw, percent=True) <= 5:
                    self.settings['v_enable_5x'].set(True)
                    self.set_limit(5)
                    break
            except (ValueError, TypeError):
                pass
        self._syncing = True
        try:
            for name, (raw, enabled) in snapshot.items():
                if name == '_regions':
                    self._regions = appearance.quality({'regions': json.loads(raw)})['regions']
                    continue
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
            self._callbacks[1 if self.output_only(changed_names) else 0]()

    def reset(self, names):
        snapshot = self.snapshot()
        before = deepcopy(snapshot)
        for name in names:
            if name == '_regions':
                snapshot[name] = ('[]', None)
                continue
            snapshot[name] = (str(self.rows[name].descriptor['default']), self._bindings[name][2])
        if snapshot != before:
            self.restore(snapshot, preserve_undo=True)

    def show_menu(self):
        if self._menu is not None:
            self._menu.destroy()
        menu = self._menu = tk.Menu(self, tearoff=False, background=self._ui['panel'],
            foreground=self._ui['text'], activebackground=self._ui['select_bg'],
            activeforeground=self._ui['text'])
        menu.add_command(label=tr('parameter.copy_from_realtime'), command=self._on_copy)
        menu.add_separator()
        menu.add_command(label=tr('parameter.reset_local'), command=self.reset_all)
        menu.add_separator()
        menu.add_command(label=tr('appearance.save'), command=lambda: self.portable(False))
        menu.add_command(label=tr('appearance.load'), command=lambda: self.portable(True))
        menu.update_idletasks()
        x = max(self.winfo_rootx(), self.more_button.winfo_rootx() + self.more_button.winfo_width()
                - menu.winfo_reqwidth())
        try:
            menu.tk_popup(x, self.more_button.winfo_rooty() + self.more_button.winfo_height())
        finally:
            menu.grab_release()

    def reset_all(self):
        if messagebox.askokcancel(tr('parameter.reset_local'), tr('parameter.reset_local_confirm'),
                                 parent=self.winfo_toplevel()):
            self.reset((*self.rows, '_regions'))

    def portable(self, importing):
        from dlss5tool.appearance_ui import load_preset, save_preset
        try:
            if importing:
                value = load_preset(self.winfo_toplevel())
                if value:
                    self.replace_common(value['values'])
            elif self.valid():
                save_preset(self.winfo_toplevel(), self.snapshot())
        except (ValueError, TypeError, KeyError, OSError) as error:
            messagebox.showerror(tr('parameter.copy_title'), str(error), parent=self)

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
            reason = tr('parameter.composition_requires_processed') if name == 'output_mix' and not self._composition_enabled else ''
            row.set_feedback(nondefault=custom, error=error, reason=reason)
        self.summary.configure(text='' if valid else tr('parameter.local_invalid'))
        self.region_summary.configure(text=tr('realtime.workspace.regions', count=len(self._regions)))
        if valid:
            self.summary.pack_forget()
        else:
            self.summary.pack(fill='x')
        self.undo_button.configure(state='normal' if self._undo is not None or self._pending is not None else 'disabled')

    def set_limit(self, maximum):
        if getattr(self, '_maximum', None) == maximum:
            return
        self._maximum = maximum
        for name, row in self.rows.items():
            if name in {f[0] for f in FIELDS}:
                row.set_maximum(maximum)
        self.refresh()

    def set_composition_enabled(self, enabled):
        if self._composition_enabled == enabled:
            return
        self._composition_enabled = enabled
        self.refresh()

    def apply_theme(self, ui):
        self._ui = dict(ui)
        for row in self.rows.values():
            row.apply_theme(ui)
        for button in (self.more_button, self.undo_button):
            button.apply_theme(ui)
        if hasattr(self, 'region_button'):
            self.region_button.apply_theme(ui)

    def destroy(self):
        if self._region_editor:
            self._region_editor.close()
        if self._menu is not None:
            self._menu.destroy()
        for var, trace in self._traces:
            var.trace_remove('write', trace)
        self._traces.clear()
        super().destroy()
