"""Static source confirmation and a shared, letterbox-aware region editor."""
import time
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk

from dlss5tool import ui_theme, ui_icons
from dlss5tool.i18n import tr
from dlss5tool.realtime_snapshot import SnapshotJob, SnapshotError, fitted_rect, normalized_point
from dlss5tool.ui_widgets import ChromeButton, Tooltip


class SourcePreview(ttk.Frame):
    def __init__(self, parent, *, ui, get_regions, commit_regions):
        super().__init__(parent, style='Stage.TFrame')
        self._ui = dict(ui)
        self.get_regions, self.commit_regions = get_regions, commit_regions
        self.target = None
        self.key = None
        self.busy = False
        self.job = self.snapshot = self.photo = self.editor = None
        self._photo_size = None
        self._control_state = None
        self._message = tr('realtime.preview.empty')
        self._stamp = ''
        self.canvas = tk.Canvas(self, height=180, width=1, highlightthickness=1, borderwidth=0, takefocus=1)
        self.canvas.pack(fill='x', pady=(6, 0))
        self.canvas.bind('<Configure>', lambda _: self.draw())
        self.canvas.bind('<Double-Button-1>', lambda _: self.edit_regions())
        self.canvas.bind('<Return>', lambda _: self.edit_regions())
        self.actions = ttk.Frame(self, style='Stage.TFrame')
        self.actions.pack(fill='x', pady=(5, 0))
        self.actions.columnconfigure(0, weight=1)
        self.refresh_button = ChromeButton(self.actions, text=tr('realtime.preview.refresh'), command=self.request,
                                           ui=ui, icon='retry', icon_only=True, width=32)
        self.refresh_button.grid(row=0, column=1, sticky='ne', padx=(8, 0))
        self.edit_button = ChromeButton(self.actions, text=tr('realtime.preview.regions'), command=self.edit_regions,
                                        ui=ui, icon='scan', icon_only=True, width=32)
        self.edit_button.grid(row=0, column=2, sticky='ne', padx=(6, 0))
        for button in (self.refresh_button, self.edit_button):
            tip = Tooltip(button, button.cget('text'))
            button.bind('<FocusIn>', tip._show, add='+')
            button.bind('<FocusOut>', tip._hide, add='+')
            button.bind('<Unmap>', tip._hide, add='+')
            button.bind('<Destroy>', tip._hide, add='+')
        self.message = tk.StringVar(self, value=self._message)
        self.label = ttk.Label(self.actions, textvariable=self.message, style='RealtimeStageMuted.TLabel',
                               font=ui_theme.UI_FONT, justify='left', wraplength=260)
        self.label.grid(row=0, column=0, sticky='ew')
        self.label.bind('<Configure>', lambda e: self.label.configure(wraplength=max(40, e.width-4)))
        Tooltip(self.label, tr('realtime.preview.recheck_detail'))
        self.apply_theme(ui)
        self._update_controls()

    def apply_theme(self, ui):
        self._ui = dict(ui)
        self.canvas.configure(bg=ui['canvas'], highlightbackground=ui['line'], highlightcolor=ui['accent'])
        self._placeholder_icon = ui_icons.icon_photo(self.canvas, 'monitor', 28, ui['muted'])
        self.refresh_button.apply_theme(ui)
        self.edit_button.apply_theme(ui)
        self.draw()
        if self.editor:
            self.editor.close()

    def set_target(self, target, title_bar=False, *, busy=False):
        key = (target['hwnd'], target['pid'], bool(title_bar)) if target else None
        if key != self.key:
            self.cancel()
            if self.editor: self.editor.close()
            self.key, self.target = key, dict(target) if target else None
            self.snapshot = self.photo = None
            self._photo_size = None
            self._message = tr('realtime.preview.refresh_needed' if target else 'realtime.preview.empty')
            self.draw()
        if busy != self.busy:
            self.busy = busy
            if busy:
                self.cancel()
                if self.editor: self.editor.close()
            self.draw()
        self._update_controls()

    def _update_controls(self):
        states = (bool(self.target and not self.busy and not self.job), bool(self.snapshot and not self.busy and not self.job))
        if states != self._control_state:
            self.refresh_button.configure(state='normal' if states[0] else 'disabled')
            self.edit_button.configure(state='normal' if states[1] else 'disabled')
            self._control_state = states
        text = tr('realtime.preview.paused' if self.snapshot else 'realtime.preview.paused_empty') if self.busy else self._message
        try:
            count = len(self.get_regions())
            if count:
                text += '\n' + tr('realtime.workspace.regions', count=count)
        except (ValueError, TypeError):
            pass  # Do not rewrite unfinished expert coordinates.
        if self.message.get() != text: self.message.set(text)

    def request(self):
        if self.busy or not self.target: return
        self.cancel()
        if self.editor: self.editor.close()
        self.snapshot = self.photo = None
        self._photo_size = None
        self._message = tr('realtime.preview.loading')
        try:
            self.job = SnapshotJob(self.target, self.key[2])
        except Exception:
            self._message = tr('realtime.preview.error.unavailable')
        self.draw()
        self._update_controls()

    def poll(self):
        if self.job is None or self.busy: return
        try:
            snapshot = self.job.poll()
            if snapshot is None: return
            self.job = None
            self.snapshot = snapshot
            self._stamp = time.strftime('%H:%M:%S')
            self._message = tr('realtime.preview.ready', width=snapshot.source_size[0],
                               height=snapshot.source_size[1], time=self._stamp)
            try:
                if self.get_regions(): self._message += '\n' + tr('realtime.preview.recheck')
            except ValueError:
                self._message += '\n' + tr('realtime.preview.invalid_regions')
        except SnapshotError as error:
            self.job = None
            self._message = tr('realtime.preview.error.' + str(error))
        except Exception:
            self.cancel()
            self._message = tr('realtime.preview.error.unavailable')
        self.draw()
        self._update_controls()

    def cancel(self):
        if self.job:
            self.job.cancel()
            self.job = None

    def draw(self):
        self._update_controls()
        self.canvas.delete('all')
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        if self.snapshot is None:
            title = tr('realtime.preview.placeholder_busy' if self.busy else
                       'realtime.preview.placeholder_selected' if self.target else 'realtime.preview.placeholder')
            text = self.canvas.create_text(width/2, height/2+20, text=title, justify='center',
                                           width=max(30, width-24), fill=self._ui['text'], font=ui_theme.UI_FONT_BOLD)
            # A wrapped translation must not collide with the monitor glyph.
            top = self.canvas.bbox(text)[1]
            self.canvas.create_image(width/2, top-12-self._placeholder_icon.height()/2, image=self._placeholder_icon)
            return
        bounds = fitted_rect(self.snapshot.source_size, width, height)
        size = (round(bounds[2]-bounds[0]), round(bounds[3]-bounds[1]))
        if size != self._photo_size or self.photo is None:
            self.photo = ImageTk.PhotoImage(self.snapshot.image.resize(size, Image.Resampling.LANCZOS), master=self.canvas)
            self._photo_size = size
        self.canvas.create_image(bounds[0], bounds[1], anchor='nw', image=self.photo)
        try:
            for index, region in enumerate(self.get_regions()):
                x0, y0, x1, y1 = region
                points = (bounds[0]+x0*size[0], bounds[1]+y0*size[1], bounds[0]+x1*size[0], bounds[1]+y1*size[1])
                self.canvas.create_rectangle(*points, outline=self._ui['accent'], width=2)
                self.canvas.create_text(points[0]+6, points[1]+5, text=str(index+1), anchor='nw',
                                        fill=self._ui['accent'], font=ui_theme.UI_FONT_BOLD)
        except (ValueError, TypeError):
            pass  # Keep unfinished coordinate text intact, never normalize silently.

    def edit_regions(self):
        if self.busy or self.job or self.snapshot is None: return
        if self.editor:
            self.editor.window.lift(); return
        try:
            regions = self.get_regions()
        except ValueError as error:
            messagebox.showerror(tr('realtime.preview.regions'), str(error), parent=self)
            return
        self.editor = RegionEditor(self, regions)

    def close(self):
        self.cancel()
        if self.editor: self.editor.close()
        self.snapshot = self.photo = None


from dlss5tool.region_editor import RegionEditor as ImageRegionEditor


class RegionEditor(ImageRegionEditor):
    """Realtime lifecycle adapter; the shared editor never captures a window."""
    def __init__(self, owner, regions):
        def commit(values):
            owner.commit_regions(values)
            owner.draw()
        super().__init__(owner, regions, image=owner.snapshot.image, ui=owner._ui,
                         on_apply=commit, can_apply=lambda: not owner.busy,
                         on_close=lambda: setattr(owner, 'editor', None))
