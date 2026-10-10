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


class RegionEditor:
    def __init__(self, owner, regions):
        self.owner = owner
        self.regions = [list(r) for r in regions]
        self.selected = None
        self.drag = None
        self.photo = None
        self._photo_size = None
        self.window = tk.Toplevel(owner)
        self.window.title(tr('realtime.preview.regions'))
        self.window.transient(owner.winfo_toplevel())
        self.window.geometry('820x580')
        self.window.minsize(440, 340)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.configure(bg=owner._ui['panel'])
        self.window.bind('<Escape>', lambda _: self.close())
        self.window.bind('<Delete>', lambda _: self.delete())
        self.window.bind('<BackSpace>', lambda _: self.delete())
        footer = ttk.Frame(self.window, padding=10, style='Panel.TFrame'); footer.pack(side='bottom', fill='x')
        self.hint = tk.StringVar(self.window, value=tr('realtime.preview.edit_hint'))
        label = ttk.Label(footer, textvariable=self.hint, wraplength=700, justify='left', font=ui_theme.UI_FONT)
        label.pack(fill='x', pady=(0, 8))
        label.bind('<Configure>', lambda e: label.configure(wraplength=max(40, e.width-4)))
        actions = ttk.Frame(footer, style='Panel.TFrame'); actions.pack(fill='x')
        self.delete_button = ChromeButton(actions, text=tr('realtime.preview.delete'), command=self.delete, ui=owner._ui)
        self.delete_button.pack(side='left')
        ChromeButton(actions, text=tr('realtime.preview.cancel'), command=self.close, ui=owner._ui).pack(side='right')
        ChromeButton(actions, text=tr('realtime.preview.apply'), command=self.apply, variant='accent', ui=owner._ui).pack(side='right', padx=8)
        self.canvas = tk.Canvas(self.window, width=1, height=1, highlightthickness=0, bg=owner._ui['canvas'], takefocus=1)
        self.canvas.pack(fill='both', expand=True, padx=10, pady=10)
        self.canvas.bind('<Configure>', lambda _: self.draw())
        self.canvas.bind('<ButtonPress-1>', self.begin)
        self.canvas.bind('<B1-Motion>', self.move)
        self.canvas.bind('<ButtonRelease-1>', self.end)
        self.canvas.bind('<Left>', lambda _: self.nudge(-.002, 0))
        self.canvas.bind('<Right>', lambda _: self.nudge(.002, 0))
        self.canvas.bind('<Up>', lambda _: self.nudge(0, -.002))
        self.canvas.bind('<Down>', lambda _: self.nudge(0, .002))
        self.canvas.bind('<Tab>', self.next_region)
        self.draw()

    def bounds(self):
        return fitted_rect(self.owner.snapshot.source_size, self.canvas.winfo_width(), self.canvas.winfo_height())

    def draw(self):
        self.canvas.delete('all')
        bounds = self.bounds(); width, height = bounds[2]-bounds[0], bounds[3]-bounds[1]
        size = (round(width), round(height))
        if self.photo is None or size != self._photo_size:
            self.photo = ImageTk.PhotoImage(self.owner.snapshot.image.resize(size, Image.Resampling.LANCZOS), master=self.canvas)
            self._photo_size = size
        self.canvas.create_image(bounds[0], bounds[1], anchor='nw', image=self.photo)
        for index, (x0, y0, x1, y1) in enumerate(self.regions):
            points = (bounds[0]+x0*width, bounds[1]+y0*height, bounds[0]+x1*width, bounds[1]+y1*height)
            self.canvas.create_rectangle(*points, outline=self.owner._ui['accent'], width=3 if index == self.selected else 1)
            self.canvas.create_text(points[0]+6, points[1]+5, text=str(index+1), anchor='nw',
                                    fill=self.owner._ui['accent'], font=ui_theme.UI_FONT_BOLD)
            if index == self.selected:
                for x in (points[0], points[2]):
                    for y in (points[1], points[3]):
                        self.canvas.create_rectangle(x-4, y-4, x+4, y+4, fill=self.owner._ui['accent'], outline='')
        self.delete_button.configure(state='normal' if self.selected is not None else 'disabled')

    def begin(self, event):
        self.canvas.focus_set()
        point = normalized_point(event.x, event.y, self.bounds())
        if point is None: return
        x, y = point
        bounds = self.bounds(); width, height = bounds[2]-bounds[0], bounds[3]-bounds[1]
        # Selected corner handles win over hit-testing overlapping rectangles.
        if self.selected is not None:
            r = self.regions[self.selected]
            for xi in (0, 2):
                for yi in (1, 3):
                    if abs(x-r[xi])*width <= 9 and abs(y-r[yi])*height <= 9:
                        self.drag = ('resize', point, list(r), xi, yi); return
        for index in reversed(range(len(self.regions))):
            r = self.regions[index]
            if r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                self.selected = index; self.drag = ('move', point, list(r)); self.draw(); return
        if len(self.regions) >= 4:
            self.hint.set(tr('realtime.regions_limit')); return
        self.selected = len(self.regions)
        self.regions.append([x, y, x, y]); self.drag = ('new', point, None)
        self.draw()

    def move(self, event):
        if self.drag is None: return
        x, y = normalized_point(event.x, event.y, self.bounds(), clamp=True)
        kind, start, original, *corner = self.drag
        if kind == 'new':
            r = [min(start[0], x), min(start[1], y), max(start[0], x), max(start[1], y)]
        elif kind == 'move':
            dx = max(-original[0], min(1-original[2], x-start[0]))
            dy = max(-original[1], min(1-original[3], y-start[1]))
            r = [original[0]+dx, original[1]+dy, original[2]+dx, original[3]+dy]
        else:
            r = list(original); xi, yi = corner
            r[xi], r[yi] = x, y
            r = [min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3])]
        self.regions[self.selected] = r
        self.draw()

    def end(self, event):
        if self.drag is None: return
        self.move(event)
        bounds = self.bounds(); r = self.regions[self.selected]
        if (r[2]-r[0])*(bounds[2]-bounds[0]) < 3 or (r[3]-r[1])*(bounds[3]-bounds[1]) < 3:
            if self.drag[0] == 'new':
                self.regions.pop(self.selected); self.selected = None
            else: self.regions[self.selected] = self.drag[2]
        self.drag = None
        self.draw()

    def next_region(self, _=None):
        if self.regions:
            self.selected = 0 if self.selected is None else (self.selected+1) % len(self.regions)
            self.draw()
        return 'break'

    def nudge(self, dx, dy):
        if self.selected is None: return
        r = self.regions[self.selected]
        dx = max(-r[0], min(1-r[2], dx)); dy = max(-r[1], min(1-r[3], dy))
        self.regions[self.selected] = [r[0]+dx, r[1]+dy, r[2]+dx, r[3]+dy]
        self.draw()

    def delete(self):
        if self.selected is not None:
            self.regions.pop(self.selected); self.selected = None; self.drag = None; self.draw()
            self.hint.set(tr('realtime.preview.edit_hint'))

    def apply(self):
        if self.owner.busy or self.drag is not None: return
        self.owner.commit_regions([[round(v, 6) for v in r] for r in self.regions])
        self.owner.draw()
        self.close()

    def close(self):
        self.owner.editor = None
        self.photo = None
        self.window.destroy()
