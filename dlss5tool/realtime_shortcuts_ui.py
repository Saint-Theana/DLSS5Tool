"""Small, keyboard-accessible editor; registration stays in the host controller."""
import tkinter as tk
from tkinter import ttk
from dlss5tool import ui_theme
from dlss5tool.i18n import tr
from dlss5tool.realtime_shortcuts import ACTION_LABELS, validate_hotkeys, effective_bindings
from dlss5tool.ui_widgets import ChromeButton, ChromeEntry


class ShortcutDialog:
    def __init__(self, owner):
        self.owner = owner
        self.window = tk.Toplevel(owner.window)
        self.window.title(tr('realtime.shortcuts.title'))
        self.window.transient(owner.window.winfo_toplevel())
        self.window.configure(background=owner._ui['panel'])
        self.window.resizable(True, False)
        ui_theme.apply_app_icon(self.window)
        body = ttk.Frame(self.window, padding=18, style='Panel.TFrame')
        body.pack(fill='both', expand=True)
        body.columnconfigure(1, weight=1)
        instructions = ttk.Label(body, text=tr('realtime.shortcuts.instructions'), style='Hint.TLabel',
                                 wraplength=560, justify='left')
        instructions.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 14))
        self.values, self.fields, self.states = {}, {}, {}
        for row, (action, title) in enumerate(ACTION_LABELS.items(), 1):
            ttk.Label(body, text=tr(title)).grid(row=row, column=0, sticky='w', padx=(0, 16), pady=6)
            value = self.values[action] = tk.StringVar(self.window, value=owner.client.hotkeys[action])
            entry = self.fields[action] = ChromeEntry(body, textvariable=value, width=24, ui=owner._ui)
            entry.grid(row=row, column=1, sticky='ew', pady=6)
            state = self.states[action] = tk.StringVar(self.window)
            ttk.Label(body, textvariable=state, style='Hint.TLabel').grid(row=row, column=2, sticky='w', padx=(12, 0))
        self.message = tk.StringVar(self.window, value=tr('realtime.shortcuts.hint'))
        message = ttk.Label(body, textvariable=self.message, wraplength=560, justify='left', style='Hint.TLabel')
        message.grid(row=5, column=0, columnspan=3, sticky='ew', pady=(10, 12))
        actions = ttk.Frame(body, style='Panel.TFrame')
        actions.grid(row=6, column=0, columnspan=3, sticky='e')
        ChromeButton(actions, text=tr('realtime.shortcuts.close'), command=self.window.destroy,
                     variant='tool', ui=owner._ui).pack(side='left', padx=6)
        self.apply = ChromeButton(actions, text=tr('realtime.shortcuts.apply'), command=self.save,
                                  variant='accent', ui=owner._ui)
        self.apply.pack(side='left')
        self.window.bind('<Escape>', lambda _: self.window.destroy())
        self.window.bind('<Return>', lambda _: self.save())
        self.refresh_status()
        self.window.update_idletasks()
        width = max(round(650 * owner._layout_scale), self.window.winfo_reqwidth())
        instructions.configure(wraplength=width - 36)
        message.configure(wraplength=width - 36)
        self.window.update_idletasks()
        height = self.window.winfo_reqheight()
        parent = owner.window.winfo_toplevel()
        x = max(0, parent.winfo_rootx() + (parent.winfo_width() - width) // 2)
        y = max(0, parent.winfo_rooty() + (parent.winfo_height() - height) // 2)
        self.window.geometry(f'{width}x{height}+{x}+{y}')
        self.window.minsize(width, height)
        # Do not wrap from a label's own Configure event: grid's requested
        # width and wrapping can oscillate forever during update_idletasks.
        def resize_message(*_):
            self.window.after_idle(lambda: self.window.geometry(
                f'{max(width, self.window.winfo_width())}x{max(height, self.window.winfo_reqheight())}')
                if self.window.winfo_exists() else None)
        self.message.trace_add('write', resize_message)
        self.window.after_idle(lambda: ui_theme.apply_native_titlebar(
            self.window, owner._ui, owner._ui.get('name') != 'light') if self.window.winfo_exists() else None)

    def refresh_status(self):
        ready = self.owner._host_ready or {}
        bindings = effective_bindings(ready)
        for action, state in self.states.items():
            ok = ready.get('hotkeys', {}).get(action)
            state.set(tr('realtime.shortcuts.available' if ok is True else
                         'realtime.shortcuts.unavailable' if ok is False else 'realtime.shortcuts.unchecked'))
            # These are the applied values, not registration claims about drafts.
            if ok is not None:
                state.set(bindings[action] + ' · ' + state.get())
        locked = self.owner.session_summary()[1] or self.owner._shortcut_changing
        self.apply.configure(state='disabled' if locked else 'normal')
        for entry in self.fields.values():
            entry.configure(state='disabled' if locked else 'normal')
        if self.owner.session_summary()[1]:
            self.message.set(tr('realtime.shortcuts.stop_first'))

    def save(self):
        if self.owner.session_summary()[1] or self.owner._shortcut_changing:
            self.refresh_status()
            return
        try:
            bindings = validate_hotkeys({key: var.get() for key, var in self.values.items()})
            if self.owner._change_shortcuts(bindings):
                self.message.set(tr('realtime.shortcuts.checking'))
                self.apply.configure(state='disabled')
        except ValueError as error:
            self.message.set(str(error))

    def finish(self, message):
        self.message.set(message)
        for key, value in self.owner.client.hotkeys.items():
            self.values[key].set(value)
        self.refresh_status()
