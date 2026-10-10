"""Image-only region editor shared by local and realtime adapters."""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from dlss5tool import ui_theme
from dlss5tool.i18n import tr
from dlss5tool.region_geometry import fitted_rect, normalized_point
from dlss5tool.ui_widgets import ChromeButton


class RegionEditor:
    def __init__(self, owner, regions, *, image, ui, on_apply, can_apply=lambda: True, on_close=lambda: None):
        self.image = image.copy()
        self._ui = dict(ui)
        self.on_apply, self.can_apply, self.on_close = on_apply, can_apply, on_close
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
        self.window.configure(bg=self._ui['panel'])
        self.window.bind('<Escape>', lambda _: self.close())
        self.window.bind('<Delete>', lambda _: self.delete())
        self.window.bind('<BackSpace>', lambda _: self.delete())
        footer = ttk.Frame(self.window, padding=10, style='Panel.TFrame'); footer.pack(side='bottom', fill='x')
        self.hint = tk.StringVar(self.window, value=tr('realtime.preview.edit_hint'))
        label = ttk.Label(footer, textvariable=self.hint, wraplength=700, justify='left', font=ui_theme.UI_FONT)
        label.pack(fill='x', pady=(0, 8))
        label.bind('<Configure>', lambda e: label.configure(wraplength=max(40, e.width-4)))
        actions = ttk.Frame(footer, style='Panel.TFrame'); actions.pack(fill='x')
        self.delete_button = ChromeButton(actions, text=tr('realtime.preview.delete'), command=self.delete, ui=self._ui)
        self.delete_button.pack(side='left')
        ChromeButton(actions, text=tr('realtime.preview.cancel'), command=self.close, ui=self._ui).pack(side='right')
        ChromeButton(actions, text=tr('realtime.preview.apply'), command=self.apply, variant='accent', ui=self._ui).pack(side='right', padx=8)
        self.canvas = tk.Canvas(self.window, width=1, height=1, highlightthickness=0, bg=self._ui['canvas'], takefocus=1)
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
        return fitted_rect(self.image.size, self.canvas.winfo_width(), self.canvas.winfo_height())

    def draw(self):
        self.canvas.delete('all')
        bounds = self.bounds(); width, height = bounds[2]-bounds[0], bounds[3]-bounds[1]
        size = (round(width), round(height))
        if self.photo is None or size != self._photo_size:
            self.photo = ImageTk.PhotoImage(self.image.resize(size, Image.Resampling.LANCZOS), master=self.canvas)
            self._photo_size = size
        self.canvas.create_image(bounds[0], bounds[1], anchor='nw', image=self.photo)
        for index, (x0, y0, x1, y1) in enumerate(self.regions):
            points = (bounds[0]+x0*width, bounds[1]+y0*height, bounds[0]+x1*width, bounds[1]+y1*height)
            self.canvas.create_rectangle(*points, outline=self._ui['accent'], width=3 if index == self.selected else 1)
            self.canvas.create_text(points[0]+6, points[1]+5, text=str(index+1), anchor='nw',
                                    fill=self._ui['accent'], font=ui_theme.UI_FONT_BOLD)
            if index == self.selected:
                for x in (points[0], points[2]):
                    for y in (points[1], points[3]):
                        self.canvas.create_rectangle(x-4, y-4, x+4, y+4, fill=self._ui['accent'], outline='')
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
        if not self.can_apply() or self.drag is not None: return
        self.on_apply([[round(v, 6) for v in r] for r in self.regions])
        self.close()

    def close(self):
        self.on_close()
        self.photo = None
        self.window.destroy()
