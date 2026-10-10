"""Small shared adapters for explicit grouped copying and portable presets."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, simpledialog, filedialog
from dlss5tool import appearance
from dlss5tool.i18n import tr
from dlss5tool.parameter_transfer import portable_preset, read_portable


def choose_groups(parent, available=appearance.GROUPS):
    class Groups(simpledialog.Dialog):
        def body(self, master):
            self.variables = {key: tk.BooleanVar(master, value=key != 'regions') for key in available}
            for key, var in self.variables.items():
                ttk.Checkbutton(master, text=tr('appearance.' + key), variable=var).pack(anchor='w', pady=5)
            ttk.Label(master, text=tr('appearance.copy_hint'), wraplength=380, justify='left').pack(pady=10)
        def validate(self):
            return any(v.get() for v in self.variables.values())
        def apply(self):
            self.result = tuple(k for k, v in self.variables.items() if v.get())
    return Groups(parent, tr('appearance.groups')).result


def save_preset(parent, snapshot):
    groups = choose_groups(parent)
    if not groups:
        return
    value = portable_preset(snapshot, groups)
    path = filedialog.asksaveasfilename(parent=parent, title=tr('appearance.save'), defaultextension='.json',
                                      filetypes=[('JSON', '*.json')])
    if path:
        # User explicitly selected this destination; no runtime/device fields.
        Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def load_preset(parent):
    path = filedialog.askopenfilename(parent=parent, title=tr('appearance.load'), filetypes=[('JSON', '*.json')])
    if not path:
        return None
    source = Path(path)
    if source.stat().st_size > 65536:
        raise ValueError('Appearance preset exceeds 64 KiB')
    value = read_portable(json.loads(source.read_text(encoding='utf-8')))
    groups = choose_groups(parent, value['groups'])
    return portable_preset(value['values'], groups) if groups else None
