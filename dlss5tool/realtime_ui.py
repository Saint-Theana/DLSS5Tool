"""Embeddable realtime workspace; pixels stay in the native presentation path."""
from copy import deepcopy
import json
import math
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog, scrolledtext
from dlss5tool import ui_theme, paths, mod_paths, support_diagnostics
from dlss5tool.i18n import tr
from dlss5tool.realtime_labels import (effect_text, parameter_label, effect_title, inspector_groups,
                                     EFFECT_CATEGORIES, effect_category, effect_description, parameter_hint)
from dlss5tool.realtime_controls import EffectChainCards, HoverHelp, InlineHelp, InspectorChoice, InspectorSection, ParameterRow
from dlss5tool.realtime_effects import (RECIPES, PURPOSES, algorithm_group, grouped_algorithms,
                                     recipe_effects, new_effect, is_frame_generation, step_title, step_subtitle, choice_issue)
from dlss5tool.realtime_readiness import StartIssue, chain_summary, check_start
from dlss5tool.realtime_logs import compact, event_summary, native_message
from dlss5tool.ui_widgets import (ChromeButton, ChromeEntry, CheckToggle, ChipGroup, CollapsibleSection,
                                  StudioNotebook, Tooltip)

from dlss5tool.realtime import (DEFAULT_CONFIG, NR, RealtimeClient, PresetStore,
                               list_windows, target_window_state, validate_config, merge_overlay_effects,
                               nr_preset, apply_nr_preset, performance_profile, sample_gpu_load, portable_config)
from dlss5tool.realtime import NR_SKIN_PAIRS, NR_SWITCH_PARAMETERS, effective_nr_skin, restore_nr_skin_memory
from dlss5tool.realtime import NR_RANGE_PARAMETERS, nr_extended_range
from dlss5tool.parameter_values import parse_number
from dlss5tool.divider_preview import DividerPreview


class RealtimeWorkspace:
    def __init__(self, parent, settings=None, *, ui=None, on_session_change=None, inspector_width=360,
                 log_parent=None, on_export_diagnostics=None, can_start=None, on_nr_settings=None, on_copy_local=None):
        self.window = ttk.Frame(parent, style='Workspace.TFrame')
        self._ui = dict(ui or ui_theme.tokens('dark'))
        self._on_session_change = on_session_change
        self._on_export_diagnostics = on_export_diagnostics
        self._can_start = can_start
        self._on_nr_settings = on_nr_settings
        self._host_ready = None
        self._preflight_issues = []
        self._preflight_signature = None
        self._diagnosing = False
        self._scroll_canvases = {}
        self._scroll_bars = {}
        self._theme_widgets = []
        self._parameter_widgets = []
        self.parameter_rows = {}
        self.parameter_sections = {}
        self.pass_toggles = {}
        self.skin_pairs = {}
        self.parameter_toggles = {}
        self.extended_range = None
        self._range_index = None
        self._parameter_groups = {}
        self._edit_snapshot = None
        self._pending_undo = self._undo_parameters = None
        self._section_open = {}
        self._editor_building = True
        self._edit_error = ''
        self._queued_parameter_apply = False
        self._queued_quality_apply = False
        self._live_sent_at = 0
        self._effect_ids = []
        self._guided_groups = {}
        self._guided_ids = []
        self._replace_index = None
        self._chain_undo = None
        self._native_state = 0
        self._session_target = None
        self._stop_requested = False
        self._render_confirmed = False
        self.client = RealtimeClient(settings)
        try:
            self.store = PresetStore()
        except Exception:
            self.window.destroy()
            raise
        self.config = deepcopy(self.store.data.get('session', DEFAULT_CONFIG))
        directory = self.store.data.get('local', {}).get('runtime_directory')
        if directory:
            self.client.settings['realtime_runtime_directory'] = directory
        self.catalog = {}
        self._catalog_generation = None
        self.windows = []
        self.controls = {}
        self._display_targets = {}
        self.parameters = {}
        self.scale_controls = None
        self.quality_controls = {}
        self.quality_rows = {}
        self._run_id = None
        self._running_config = None
        self._pending_start = None
        self._start_seen = False
        self._known_good = None
        self._rollback_used = False
        self._pending_command = None
        self._pending_since = 0
        self._pending_quality = None
        self._known_settings = None
        self._recovery = queue.Queue()
        self._recovering = False
        self._recovery_target = None
        self._parameter_modes = {}
        self._applied_effects = []
        self._live_expected = {}
        self._live_commands = set()
        self._overlay_expected = {}
        self._overlay_sent_at = 0
        self._overlay_saved = None
        self._gpu_sampling = False
        self._last_gpu_sample = 0
        self._last_metrics = None
        self._metrics_compact = ''
        self._metrics_run_id = None
        self._last_status_request = 0
        self.diagnostics = support_diagnostics.EventJournal()
        self._after = None
        self._closed = False
        self._active = False
        scale = getattr(parent.winfo_toplevel(), '_studio_scale', 1.0)
        self._layout_scale = scale
        self._inspector_default = inspector_width
        self._inspector_user_width = None
        self._splitter_drag = None
        self._splitter_pending_width = None
        self._splitter_hover = False
        self.inspector = ttk.Frame(self.window, style='Panel.TFrame', width=round(inspector_width * scale))
        self.inspector.pack(side='right', fill='y')
        self.inspector.pack_propagate(False)
        self.window.bind('<Configure>', self._size_inspector)
        self.splitter = tk.Frame(self.inspector, width=max(6, round(6 * scale)),
                                 cursor='sb_h_double_arrow', bg=self._ui['line'],
                                 borderwidth=0, highlightthickness=0, takefocus=1)
        self.splitter.pack(side='left', fill='y')
        # A placed sibling overlays the panes without taking part in layout.
        self._splitter_preview = DividerPreview(self.window, self._ui['accent'])
        self.splitter.bind('<Button-1>', self._splitter_start)
        self.splitter.bind('<B1-Motion>', self._splitter_move)
        self.splitter.bind('<ButtonRelease-1>', self._splitter_end)
        self.splitter.bind('<Double-Button-1>', self._splitter_reset)
        self.splitter.bind('<Left>', lambda _: self._splitter_nudge(16))
        self.splitter.bind('<Right>', lambda _: self._splitter_nudge(-16))
        self.splitter.bind('<Home>', self._splitter_reset)
        self.splitter.bind('<Escape>', self._splitter_cancel)
        self.splitter.bind('<Unmap>', self._splitter_cancel)
        self.splitter.bind('<Enter>', lambda _: self._paint_splitter(True))
        self.splitter.bind('<Leave>', lambda _: self._paint_splitter(False))
        self.splitter.bind('<FocusIn>', lambda _: self._paint_splitter())
        self.splitter.bind('<FocusOut>', self._splitter_cancel)
        self._hover_help(self.splitter, tr('realtime.layout.resize_hint'))
        stage = self.stage = ttk.Frame(self.window, style='Stage.TFrame')
        stage.pack(side='left', fill='both', expand=True)
        # Keep stop, actual-session status and errors outside the scroll area.
        footer = self.stage_footer = ttk.Frame(stage, padding=12, style='Stage.TFrame')
        footer.pack(side='bottom', fill='x')
        self.stage_scroll = ttk.Frame(stage, style='Stage.TFrame')
        self.stage_scroll.pack(fill='both', expand=True)
        self.stage_content = self._scroll_content(self.stage_scroll, stage=True)
        self.stage_canvas = self.stage_content.master
        header = ttk.Frame(self.stage_content, style='Stage.TFrame')
        header.pack(fill="x")
        self._label(header, tr("realtime.title"), font=ui_theme.UI_FONT_TITLE)
        self._label(header, tr('realtime.layout.source'), muted=True)
        target_row = ttk.Frame(header, style='Stage.TFrame')
        target_row.pack(fill="x", pady=(8, 0))
        self.target = self._combo(target_row, state="readonly", width=12)
        self.target.pack(side="left", fill="x", expand=True)
        self.target.bind("<<ComboboxSelected>>", self._target_changed)
        self._button(target_row, tr("realtime.refresh"), self.refresh).pack(side="left", padx=6)
        self.target_hint = tk.StringVar(self.window)
        self._label(header, variable=self.target_hint, muted=True)
        self.status = tk.StringVar(value=tr("realtime.not_started"))
        self._status_trace = self.status.trace_add('write', self._record_status)

        self.recipe_frame = ttk.Frame(header, padding=(0, 8, 0, 0), style='Stage.TFrame')
        self.recipe_frame.pack(fill='x')
        output_row = self.output_row = ttk.Frame(header, padding=(0, 8, 0, 0), style='Stage.TFrame')
        output_row.pack(fill='x')
        self.check_button = self._button(header, tr('realtime.preflight.check'), self.check_before_start, 'tool')
        self.check_button.pack(anchor='e', pady=(4, 0))
        self.session_text = tk.StringVar(self.window)
        self.session_label = self._label(footer, variable=self.session_text, font=ui_theme.UI_FONT_BOLD)
        self._hover_help(self.session_label, tr('realtime.layout.native_output'))
        self.stop_hint = tk.StringVar(self.window, value=tr('realtime.safety.checking'))
        self.stop_hint_label = self._label(footer, variable=self.stop_hint, muted=True)
        Tooltip(self.stop_hint_label, tr('realtime.safety.protected_detail'))
        notice = ttk.Frame(footer, style='Stage.TFrame')
        notice.pack(fill='x')
        self.status_label = self._label(notice, variable=self.status, muted=True)
        self.metrics_summary = tk.StringVar(value=tr('realtime.metrics_idle'))
        self.metrics_label = self._label(footer, variable=self.metrics_summary, muted=True)
        Tooltip(self.metrics_label, tr('realtime.metrics_hint'))
        run_actions = ttk.Frame(footer, style='Stage.TFrame')
        run_actions.pack(fill='x', pady=(4, 0))
        self.start_button = self._button(run_actions, tr("realtime.start"), self.start, 'accent')
        self.start_button.pack(side='left', fill='x', expand=True)
        self.stop_button = self._button(run_actions, tr("realtime.stop"), lambda: self.command('stop'), 'danger')
        self.stop_button.pack(side='left', padx=(8, 0))
        self.preflight_panel = ttk.Frame(header, style='Stage.TFrame')
        self.preflight_status = tk.StringVar(self.window)
        self._label(self.preflight_panel, variable=self.preflight_status, muted=True)
        self.preflight_choice = self._combo(self.preflight_panel, state='readonly', width=12)
        self.preflight_choice.pack(fill='x')
        self.preflight_choice.bind('<<ComboboxSelected>>', self._show_preflight_issue)
        self.preflight_message = tk.StringVar(self.window)
        issue_label = self._label(self.preflight_panel, variable=self.preflight_message)
        self._preflight_tooltip = Tooltip(issue_label, '')
        fixes = ttk.Frame(self.preflight_panel, style='Stage.TFrame')
        fixes.pack(fill='x')
        self.locate_button = self._button(fixes, tr('realtime.preflight.locate'), self._locate_preflight, 'tool')
        self.locate_button.pack(side='left')
        self.continue_button = self._button(fixes, tr('realtime.preflight.continue'), lambda: self.start(accept_warnings=True), 'tool')
        self._button(fixes, tr('realtime.help.hide'), lambda: self.preflight_panel.pack_forget(), 'tool').pack(side='right')

        info = ttk.Frame(self.stage_content, padding=(0, 4), style='Stage.TFrame')
        info.pack(fill='x')
        self.metrics_section = self._section(info, tr('realtime.metrics_details'))
        self.metrics = tk.StringVar(value=tr("realtime.metrics_hint"))
        self._label(self.metrics_section.body, variable=self.metrics, muted=True)
        self.gpu_load = tk.StringVar(value=tr("realtime.gpu_hint"))
        self._label(self.metrics_section.body, variable=self.gpu_load, muted=True)
        self._hover_help(self.metrics_section._header, tr('realtime.metrics_hint') + '\n' + tr('realtime.gpu_hint'))

        surface = ttk.Frame(self.stage_content, padding=(0, 8), style='Stage.TFrame')
        surface.pack(fill='x', before=info)
        self._label(surface, tr('realtime.layout.output_tools'), font=ui_theme.UI_FONT_BOLD)
        presentation = ttk.Frame(surface, style='Stage.TFrame')
        presentation.pack(fill='x', pady=(4, 8))
        self.presentation_buttons = {}
        for i, (label, action) in enumerate(((tr("realtime.compare"), 'compare'), (tr("realtime.overlay_parameters"), 'parameters'),
                                            (tr("realtime.profiler"), 'profiler'), (tr("realtime.screenshot"), 'screenshot'))):
            presentation.columnconfigure(i % 2, weight=1)
            action_button = self._button(presentation, label, lambda a=action: self.command(a))
            self.presentation_buttons[action] = action_button
            action_button.grid(
                row=i // 2, column=i % 2, sticky='ew', padx=2, pady=2)
            if action == 'parameters':
                self._control_tip = Tooltip(action_button, tr('realtime.control.help'))

        inspector_footer = self.editor_footer = ttk.Frame(self.inspector, padding=10, style='Panel.TFrame')
        inspector_footer.pack(side='bottom', fill='x')
        self.editor_status = tk.StringVar(self.window, value=tr('realtime.editor.idle'))
        self.editor_status_label = self._label(inspector_footer, variable=self.editor_status, muted=True)
        self.apply_button = self._button(inspector_footer, tr('realtime.editor.apply'), self._apply_editor, 'accent')
        self.apply_button.pack(fill='x', pady=(4, 0))
        Tooltip(self.apply_button, tr('realtime.independent_hint'))
        self.tabs = tabs = StudioNotebook(self.inspector, ui=self._ui)
        tabs.pack(fill='both', expand=True)
        self._theme_widgets.append(tabs)
        effect_page = self._scroll_page(tabs, tr("realtime.tab.effects"))
        display_page = self._scroll_page(tabs, tr('realtime.layout.output'))
        advanced_page = self._scroll_page(tabs, tr('realtime.layout.advanced'))
        self._pages = dict(effects=effect_page, protection=effect_page, display=display_page,
                           runtime=advanced_page, startup=self.stage_content)

        self._build_recipe_picker(self.recipe_frame)
        self.presets_section = self._section(self.recipe_frame, tr('realtime.layout.presets'))
        preset_page = self.presets_section.body
        parameter_actions = ttk.Frame(effect_page, style='Panel.TFrame')
        parameter_actions.pack(fill='x', pady=(4, 0))
        self.parameter_heading = self._hint(parameter_actions, '', '', heading=True)
        self.undo_button = self._button(self.parameter_heading.row, tr('realtime.editor.undo_short'), self._undo_parameter_edit, 'tool', icon='undo', icon_only=True)
        self.undo_button.pack(side='right', padx=(4, 0), before=self.parameter_heading.label)
        self._hover_help(self.undo_button, tr('realtime.editor.undo_hint'))
        self.parameter_frame = ttk.Frame(effect_page, style='Panel.TFrame')
        self.parameter_frame.pack(fill='x')
        self.fluency_section = self._section(effect_page, tr('realtime.workflow.fluency'))
        self._build_fluency(self.fluency_section.body)
        self.residual_section = self._section(effect_page, tr('realtime.residual'))
        self.protection_section = self._section(effect_page, tr('realtime.layout.protection'))
        quality_page = self.protection_section.body
        self.workflow_section = self._section(effect_page, tr('realtime.layout.workflow'))
        left = self.workflow_section.body
        actions = ttk.Frame(left, style='Panel.TFrame')
        actions.pack(fill='x')
        for title, action in ((tr('realtime.move_down'), lambda: self._move(1)),
                              (tr('realtime.move_up'), lambda: self._move(-1))):
            self._button(actions, title, action, 'tool').pack(side='right', padx=(4, 0))
        self.chain_help = self._hint(actions, tr('realtime.chain'), tr('realtime.effects.chain_hint'))
        self.chain_help.pack_configure(side='left', fill='x', expand=True)
        self.chain = EffectChainCards(left, ui=self._ui, on_edit=self._focus_parameters,
                                     on_replace=self._choose_replacement, on_remove=self._remove)
        self._theme_widgets.append(self.chain)
        self.chain.pack(fill="x", pady=6)
        self.chain.bind("<<ListboxSelect>>", self._select_effect)
        self.draft_summary = tk.StringVar(self.window)
        self.running_summary = tk.StringVar(self.window)
        self.chain_summary_help = self._hint(left, tr('realtime.summary.difference'), '')
        self.add_section = CollapsibleSection(left, tr('realtime.workflow.add_step'), collapsed=True, ui=self._ui)
        self.add_section.pack(fill='x', pady=(0, 6))
        self._theme_widgets.append(self.add_section)
        self._build_guided_picker(self.add_section.body)
        self.library_section = CollapsibleSection(self.add_section.body, tr('realtime.workflow.library'), collapsed=True, ui=self._ui)
        self.library_section.pack(fill='x', pady=(8, 0))
        self._theme_widgets.append(self.library_section)
        library = self.library_section.body
        self.effect_category = self._combo(library, state='readonly', width=12,
                                          values=[tr('realtime.effects.category.' + key) for key in EFFECT_CATEGORIES])
        self.effect_category.current(0)
        self.effect_category.pack(fill='x', pady=(0, 6))
        self.effect_category.bind('<<ComboboxSelected>>', lambda _: self._filter_effects())
        self._label(library, tr('realtime.editor.search'), muted=True)
        self.effect_search = tk.StringVar(self.window)
        self._entry_field(library, textvariable=self.effect_search, width=12).pack(fill='x', pady=(0, 6))
        self.favorites_only = tk.BooleanVar(self.window, value=False)
        self._check(library, tr('realtime.workflow.favorites_only'), self.favorites_only, self._filter_effects).pack(anchor='w')
        picker = ttk.Frame(library, style='Panel.TFrame')
        picker.pack(fill='x')
        self.library_add = self._button(picker, tr('realtime.editor.add'), self._add)
        self.library_add.pack(side='right', padx=(6, 0))
        self.effect_choice = self._combo(picker, state='readonly', width=12)
        self.effect_choice.pack(side='left', fill='x', expand=True)
        self.effect_choice.bind('<<ComboboxSelected>>', lambda _: self._describe_effect_choice())
        self.effect_count = tk.StringVar(self.window)
        self.effect_help = tk.StringVar(self.window, value=tr('realtime.effects.choose_hint'))
        self._label(library, variable=self.effect_count, muted=True)
        self.favorite_button = self._button(library, tr('realtime.workflow.favorite'), self._toggle_favorite, 'tool')
        self.favorite_button.pack(anchor='e')
        self.effect_help_widget = self._hint(library, '', tr('realtime.effects.choose_hint'), variable=self.effect_help)
        self.effect_search.trace_add('write', lambda *_: self._filter_effects())
        if on_copy_local is not None:
            copy_button = self._button(preset_page, tr('realtime.copy_local_short'), on_copy_local, 'tool')
            copy_button.pack(fill='x', pady=4)
            Tooltip(copy_button, tr('parameter.copy_from_local'))

        self._label(output_row, tr('realtime.output.mode'))
        self.output_mode = tk.BooleanVar(self.window, value=self.config['windowed'])
        self.controls['windowed'] = (self.output_mode, 'bool')
        self.output_selector = ChipGroup(output_row, self.output_mode,
            {False: tr('realtime.output.fullscreen'), True: tr('realtime.output.windowed')},
            command=self._output_changed, ui=self._ui, connected=True)
        self.output_selector.pack(anchor='w')
        self._theme_widgets.append(self.output_selector)
        Tooltip(self.output_selector, tr('realtime.output.help'))
        self.output_hint = tk.StringVar(self.window)
        self._hint(output_row, '', tr('realtime.output.help'), variable=self.output_hint)
        self.output_details_button = self._button(output_row, tr('realtime.layout.output_settings'),
                                                  lambda: self._focus_page('display'), 'tool')
        self.output_details_button.pack(anchor='w', pady=(4, 0))
        self.output_summary = tk.StringVar(self.window)
        self._label(display_page, variable=self.output_summary, muted=True)
        self._choice(advanced_page, tr("realtime.capture_method"), "capture_method", [tr("realtime.capture.wgc"), tr("realtime.capture.dd"), "GDI", tr("realtime.capture.dwm")])
        self.controls['capture_method'][0].bind('<<ComboboxSelected>>', lambda _: self._output_changed())
        self._choice(display_page, tr("realtime.monitor_mode"), "monitor_mode", [tr("realtime.monitor.nearest"), tr("realtime.monitor.intersecting"), tr("realtime.monitor.all"), tr("realtime.monitor.specific")])
        self._entry(display_page, tr("realtime.monitor_id"), "monitor_id")
        self._entry(advanced_page, tr("realtime.gpu_index"), "gpu_index")
        self._entry(display_page, tr("realtime.window_scale"), "window_scale")
        self._choice(advanced_page, tr("realtime.gpu_priority"), 'gpu_priority', [tr("realtime.priority.normal"), tr("realtime.priority.enhancement"), tr("realtime.priority.game")])
        self.monitor_picker = self._combo(display_page, state='readonly', width=12)
        self.monitor_picker.pack(fill='x', pady=4)
        self.monitor_picker.bind('<<ComboboxSelected>>', self._pick_monitor)
        self.gpu_picker = self._combo(advanced_page, state='readonly', width=12)
        self.gpu_picker.pack(fill='x', pady=4)
        self.gpu_picker.bind('<<ComboboxSelected>>', self._pick_gpu)
        self._choice(display_page, tr("realtime.sync_mode"), "sync_mode", [tr("realtime.sync.front"), tr("realtime.sync.async"), tr("realtime.sync.reflex")])
        self._entry(display_page, tr("realtime.frame_rate"), "frame_rate")
        profiles = ttk.Frame(display_page); profiles.pack(fill='x', pady=5)
        for i, (name, label) in enumerate((('balanced', tr("realtime.profile.balanced")), ('game', tr("realtime.profile.game")), ('eco', tr("realtime.profile.eco")), ('quality', tr("realtime.profile.display")))):
            profiles.columnconfigure(i % 2, weight=1)
            self._button(profiles, label, lambda n=name: self.apply_profile(n)).grid(row=i // 2, column=i % 2, sticky='ew', padx=2, pady=2)
        for label, key in ((tr("realtime.game_mode"), "game_mode"),
                           (tr("realtime.hdr"), "hdr"), (tr("realtime.sync_enabled"), "sync_enabled"),
                           (tr("realtime.capture_title"), "capture_title_bar"), (tr("realtime.not_topmost"), "disable_topmost")):
            var = tk.BooleanVar(value=self.config[key])
            self.controls[key] = (var, "bool")
            widget = self._check(advanced_page if key in ('game_mode', 'capture_title_bar') else display_page, label, var, self._editor_changed)
            widget.pack(anchor="w", pady=5)
            self._display_targets[key] = widget
        fallback = tk.BooleanVar(value=self.config['capture_fallback'])
        self.controls['capture_fallback'] = (fallback, 'bool')
        self._check(advanced_page, tr('realtime.fallback'), fallback, self._editor_changed).pack(anchor='w', pady=5)
        self._hint(advanced_page, tr('realtime.help.display'), tr('realtime.display_hint'))
        self._sync_output_controls()

        self._hover_help(self.residual_section._header, tr('realtime.residual_hint'))
        for key, label in (('total', tr("realtime.quality.total")), ('darken', tr("realtime.quality.darken")), ('brighten', tr("realtime.quality.brighten")),
                           ('color', tr("realtime.quality.color")), ('luminance', tr("realtime.quality.luminance")), ('feather', tr("realtime.quality.feather"))):
            var = tk.StringVar(value=str(self.config['quality'][key]))
            self.quality_controls[key] = var
            descriptor = dict(name=key, label=label, default=DEFAULT_CONFIG['quality'][key],
                              min=0, max=256 if key == 'feather' else 2,
                              step=1 if key == 'feather' else .05, integer=False)
            row = ParameterRow(quality_page if key == 'feather' else self.residual_section.body, descriptor, var, ui=self._ui,
                               on_commit=self._quality_committed, on_change=self._editor_changed,
                               hint=tr('realtime.quality.total_hint') if key == 'total' else '')
            row.pack(fill='x', pady=(4, 8))
            self.quality_rows[key] = row
            self._theme_widgets.append(row)
        self.quality_controls['protection'] = tk.BooleanVar(value=self.config['quality']['protection'])
        self._check(quality_page, tr('realtime.protection'), self.quality_controls['protection'], self._quality_committed).pack(anchor='w', pady=8)
        self.region_preview = tk.Canvas(quality_page, width=1, height=150, highlightthickness=0)
        self.region_preview.pack(fill='x', pady=8)
        self._drag_start = None
        self.region_preview.bind('<Configure>', lambda _: self._draw_regions())
        self.region_preview.bind('<ButtonPress-1>', self._region_begin)
        self.region_preview.bind('<B1-Motion>', self._region_drag)
        self.region_preview.bind('<ButtonRelease-1>', self._region_end)
        self._hover_help(self.protection_section._header, tr('realtime.regions_hint') + '\n' + tr('realtime.regions_format'))
        self._hover_help(self.region_preview, tr('realtime.regions_hint') + '\n' + tr('realtime.regions_format'))
        self.regions = tk.Text(quality_page, height=5, width=1)
        self.regions.pack(fill='x', pady=8)
        self.regions.insert('1.0', '\n'.join(' '.join(map(str, r)) for r in self.config['quality']['regions']))
        self._label(quality_page, tr("realtime.regions_edit"), muted=True)
        self._button(quality_page, tr('realtime.apply_quality'), self.apply_quality).pack(fill='x', pady=8)

        self._label(preset_page, tr("realtime.presets"), font=ui_theme.UI_FONT_BOLD)
        self._hint(preset_page, tr('realtime.help.presets'), tr('realtime.presets_hint'))
        self.preset_choice = self._combo(preset_page, values=sorted(self.store.data["presets"]), state="readonly", width=12)
        self.preset_choice.pack(fill='x', pady=10)
        self.bind_app = tk.BooleanVar(value=True)
        self._check(preset_page, tr('realtime.bind_app'), self.bind_app).pack(anchor="w", pady=6)
        for label, action in ((tr("realtime.load_preset"), self.load_preset), (tr("realtime.save_current"), self.save_preset),
                              (tr("realtime.export_config"), self.export_config), (tr("realtime.import_config"), self.import_config)):
            self._button(preset_page, label, action).pack(fill='x', pady=5)
        self.nr_choice = self._combo(preset_page, values=sorted(self.store.data.get('nr_presets', {})), state='readonly', width=12)
        self.nr_choice.pack(fill='x', pady=8)
        self._button(preset_page, tr('realtime.save_nr'), self.save_nr).pack(fill='x', pady=4)
        self._button(preset_page, tr('realtime.load_nr'), self.load_nr).pack(fill='x', pady=4)
        self.nr_export = tk.BooleanVar(value=False)
        self._check(preset_page, tr('realtime.export_nr'), self.nr_export).pack(anchor='w', pady=5)
        self._button(advanced_page, tr('diagnostics.export'), self.export_diagnostics).pack(fill='x', pady=6)
        # App owns visibility in the shared bottom slot; standalone harnesses
        # keep a bottom log of their own. Each mode retains its text and scroll.
        self.log = scrolledtext.ScrolledText(log_parent if log_parent is not None else self.window,
                                             height=5, width=1, wrap='word', state='disabled',
                                             font=ui_theme.UI_MONO)
        ui_theme.install_ttk_scrolledtext_scrollbar(self.log)
        if log_parent is None:
            self._button(advanced_page, tr('action.log'), self._toggle_log, 'tool').pack(fill='x', pady=4)
        self.runtime_button = self._button(advanced_page, tr('realtime.runtime_directory'), self.select_runtime)
        self.runtime_button.pack(fill='x', pady=6)
        runtime = mod_paths.runtime_info(self.client.settings)
        runtime_label = self._label(advanced_page, tr('realtime.runtime.shared', source=tr('realtime.runtime.' + runtime['source'])), muted=True)
        Tooltip(runtime_label, runtime['path'] + '\n' + tr('realtime.runtime.explanation'))
        self._hint(advanced_page, tr('realtime.help.runtime'), tr('realtime.runtime.explanation'))
        if self._on_nr_settings:
            self._button(advanced_page, tr('realtime.preflight.nr_settings'), self._on_nr_settings, 'tool').pack(fill='x', pady=4)
        self.apply_theme(self._ui)
        self._render_chain()
        self._editor_building = False
        self.refresh()
        try:
            self.client.send("catalog")
            self.client.send('devices')
        except Exception as error:
            self.status.set(str(error))
        self._poll()

    def _size_inspector(self, event):
        if event.widget is not self.window or event.width < 2:
            return
        self._splitter_cancel()
        self._layout_inspector(event.width)

    def _layout_inspector(self, total):
        # No preview canvas needs the majority of the width in this mode.
        # Automatic sizing is used only until the user moves the divider.
        scale = self._layout_scale
        width = (self._inspector_user_width * scale if self._inspector_user_width is not None
                 else min(round(total * .62), max(round(self._inspector_default * scale),
                          min(round(total * .56), round(620 * scale)))))
        self._set_inspector_width(width, remember=False, total=total)

    def _clamp_inspector_width(self, width, total=None):
        total = max(2, total if total is not None else self.window.winfo_width())
        scale = self._layout_scale
        # Reserve both panes even when shrinking a previously large window.
        left_min = min(round(320 * scale), round(total * .45))
        right_min = min(round(360 * scale), total - left_min)
        return max(right_min, min(round(width), total - left_min))

    def _set_inspector_width(self, width, *, remember=True, total=None):
        width = self._clamp_inspector_width(width, total)
        if remember:
            self._inspector_user_width = width / self._layout_scale
        if int(self.inspector.cget('width')) != width:
            self.inspector.configure(width=width)

    def _paint_splitter(self, hover=None):
        if hover is not None:
            self._splitter_hover = hover
        focused = str(self.splitter.tk.call('focus')) == str(self.splitter)
        active = self._splitter_hover or self._splitter_drag is not None or focused
        self.splitter.configure(bg=self._ui['accent'] if active else self._ui['line'])
        self._splitter_preview.configure(bg=self._ui['accent'])

    def _show_splitter_preview(self, width):
        self._splitter_pending_width = width
        self._splitter_preview.place(x=self.window.winfo_width() - width,
                                     y=self.inspector.winfo_y(),
                                     width=max(2, round(2 * self._layout_scale)),
                                     height=self.inspector.winfo_height())
        self._splitter_preview.lift()

    def _splitter_start(self, event):
        self._splitter_drag = (event.x_root, self.inspector.winfo_width())
        self.splitter.focus_set()
        self._paint_splitter()
        self._show_splitter_preview(self._splitter_drag[1])

    def _splitter_move(self, event):
        if self._splitter_drag is not None:
            origin, width = self._splitter_drag
            width = self._clamp_inspector_width(width + origin - event.x_root)
            if width != self._splitter_pending_width:
                self._show_splitter_preview(width)

    def _splitter_end(self, event=None):
        if self._splitter_drag is None:
            return
        if event is not None:
            # The release can be newer than the last delivered motion event.
            self._splitter_move(event)
        initial = self._splitter_drag[1]
        width = self._splitter_pending_width
        self._splitter_cancel()
        if width != initial:
            self._set_inspector_width(width)

    def _splitter_cancel(self, _=None):
        if self._closed:
            return 'break'
        self._splitter_drag = None
        self._splitter_pending_width = None
        self._splitter_preview.place_forget()
        self._paint_splitter()
        return 'break'

    def _splitter_nudge(self, step):
        self._splitter_cancel()
        self._set_inspector_width(self.inspector.winfo_width() + step * self._layout_scale)
        return 'break'

    def _splitter_reset(self, _=None):
        self._splitter_cancel()
        self._inspector_user_width = None
        self._layout_inspector(self.window.winfo_width())
        self._paint_splitter()
        return 'break'

    def _toggle_log(self):
        if self.log.frame.winfo_manager():
            self.log.pack_forget()
        else:
            self.log.pack(side='bottom', fill='x', before=self.inspector)

    def _section(self, parent, title):
        stage = str(parent.cget('style')) == 'Stage.TFrame'
        section = CollapsibleSection(parent, title, collapsed=True,
                                     ui=dict(self._ui, panel=self._ui['canvas']) if stage else self._ui)
        if stage:
            section.configure(style='Stage.TFrame')
            section.body.configure(style='Stage.TFrame')
        section.pack(fill='x', pady=(6, 0))
        self._theme_widgets.append(section)
        return section

    def _build_recipe_picker(self, parent):
        self._label(parent, tr('realtime.workflow.recipes'), font=ui_theme.UI_FONT_BOLD)
        row = ttk.Frame(parent, style=parent.cget('style'))
        row.pack(fill='x')
        self.recipe_button = self._button(row, tr('realtime.workflow.use_recipe'), self._use_recipe, 'tool')
        self.recipe_button.pack(side='right', padx=(6, 0))
        self.recipe_choice = self._combo(row, state='readonly', width=12,
            values=[tr('realtime.workflow.recipe.' + key) for key in RECIPES])
        self.recipe_choice.current(0)
        self.recipe_choice.pack(side='left', fill='x', expand=True)
        self.recipe_choice.bind('<<ComboboxSelected>>', lambda _: self._preview_recipe())
        self.recipe_help = tk.StringVar(self.window)
        self.recipe_help_widget = self._hint(parent, '', tr('realtime.workflow.recipe_hint'),
                                             variable=self.recipe_help)
        self.chain_undo_button = self._button(self.recipe_help_widget.row, tr('realtime.editor.undo_short'), self._undo_chain, 'tool', icon='undo', icon_only=True)
        self.chain_undo_button.pack(side='right', padx=(4, 0), before=self.recipe_help_widget.label)
        self._hover_help(self.chain_undo_button, tr('realtime.workflow.undo_chain'))

    def _build_fluency(self, parent):
        self.fg_choice = self._combo(parent, state='readonly', width=12)
        self.fg_choice.pack(fill='x', pady=(0, 8))
        self.fg_choice.bind('<<ComboboxSelected>>', self._set_fluency)
        Tooltip(self.fg_choice, tr('realtime.workflow.fluency_hint'))

    def _build_guided_picker(self, parent):
        self._label(parent, tr('realtime.workflow.purpose'), muted=True)
        self.purpose_choice = self._combo(parent, state='readonly', width=12,
            values=[tr('realtime.workflow.step.' + key) for key in PURPOSES])
        self.purpose_choice.current(0)
        self.purpose_choice.pack(fill='x')
        self.purpose_choice.bind('<<ComboboxSelected>>', lambda _: self._refresh_guided())
        self._label(parent, tr('realtime.workflow.algorithm'), muted=True)
        self.algorithm_choice = self._combo(parent, state='readonly', width=12)
        self.algorithm_choice.pack(fill='x')
        self.algorithm_choice.bind('<<ComboboxSelected>>', lambda _: self._select_algorithm())
        self.variant_box = ttk.Frame(parent, style='Panel.TFrame')
        self.variant_box.pack(fill='x')
        self._label(self.variant_box, tr('realtime.workflow.variant'), muted=True)
        self.variant_choice = self._combo(self.variant_box, state='readonly', width=12)
        self.variant_choice.pack(fill='x')
        self.variant_choice.bind('<<ComboboxSelected>>', lambda _: self._describe_guided())
        self.guided_help = tk.StringVar(self.window)
        self.guided_help_widget = self._hint(parent, '', '', variable=self.guided_help)
        row = ttk.Frame(parent, style='Panel.TFrame')
        row.pack(fill='x')
        self.guided_add = self._button(row, tr('realtime.workflow.add_step'), self._add_guided)
        self.guided_add.pack(side='left', fill='x', expand=True)
        self.cancel_replace = self._button(row, tr('realtime.workflow.cancel_replace'), self._cancel_replacement, 'tool')

    def _preview_recipe(self):
        key = RECIPES[max(0, self.recipe_choice.current())]
        if not self.catalog and key != 'custom':
            self.recipe_help.set(tr('realtime.preflight.catalog_wait'))
            self.recipe_button.configure(state='disabled')
            return
        try:
            effects = recipe_effects(key, self.catalog, self.config['effects'])
            self.recipe_help.set(chain_summary(effects, self.catalog))
            self.recipe_help_widget.set_details(tr('realtime.workflow.recipe_note.' + key) + '\n' +
                tr('realtime.workflow.recipe_hint'))
            self.recipe_button.configure(state='normal')
        except ValueError as error:
            self.recipe_help.set(str(error))
            self.recipe_button.configure(state='disabled')

    def _use_recipe(self):
        key = RECIPES[max(0, self.recipe_choice.current())]
        if key == 'custom':
            if self.add_section.collapsed:
                self.add_section.toggle()
            self._focus_page('effects', self.purpose_choice)
            return
        try:
            self._commit_effects(recipe_effects(key, self.catalog, self.collect()['effects']))
        except ValueError as error:
            self.status.set(str(error))

    def _commit_effects(self, effects, index=0):
        current = self.collect()
        candidate = deepcopy(current)
        candidate['effects'] = deepcopy(effects)
        candidate = validate_config(candidate)
        if candidate['effects'] == current['effects']:
            return
        self._chain_undo = deepcopy(current['effects'])
        self._queued_parameter_apply = False
        self.parameters = {}
        self.scale_controls = None
        self.config['effects'] = candidate['effects']
        self._replace_index = None
        self._render_chain(index)
        self.status.set(tr('realtime.workflow.draft_updated'))

    def _undo_chain(self):
        if self._chain_undo is None:
            return
        try:
            previous = deepcopy(self._chain_undo)
            self._commit_effects(previous)
            self._chain_undo = None
            self.chain_undo_button.configure(state='disabled')
        except ValueError as error:
            self.status.set(str(error))

    def _refresh_workflow(self):
        self.chain_undo_button.configure(state='normal' if self._chain_undo is not None else 'disabled')
        self._preview_recipe()
        current = [e['name'] for e in self.config['effects'] if is_frame_generation(e['name'])]
        self._fg_ids = sorted(set(name for name in self.catalog if is_frame_generation(name)) | set(current))
        self.fg_choice.configure(values=[tr('realtime.workflow.no_fg')] + [self._algorithm_label(name) for name in self._fg_ids])
        self.fg_choice.current(self._fg_ids.index(current[0]) + 1 if len(current) == 1 else 0)
        if len(current) > 1:
            self.fg_choice.set(tr('realtime.preflight.fg_conflict'))
        self._refresh_guided()
        self._describe_effect_choice()

    def _set_fluency(self, _=None):
        try:
            config = self.collect()
            index = self.fg_choice.current() - 1
            effects = [e for e in config['effects'] if not is_frame_generation(e['name'])]
            if index >= 0:
                name = self._fg_ids[index]
                issue, blocked = choice_issue(name, self.catalog, effects)
                if blocked:
                    raise ValueError(issue)
                # Keep custom ordering and settings when reselecting an FG.
                position = next((i for i, e in enumerate(config['effects']) if is_frame_generation(e['name'])), len(effects))
                effects.insert(position, next((e for e in config['effects'] if e['name'] == name), new_effect(name)))
            self._commit_effects(effects)
        except ValueError as error:
            self.status.set(str(error))
        self._refresh_workflow()

    def _algorithm_label(self, name):
        supported = self.catalog.get(name, {}).get('available', True) and name in self.catalog
        return effect_title(name, self.catalog.get(name)) + (' · ' + tr('realtime.workflow.unavailable_tag') if not supported else '')

    def _refresh_guided(self):
        previous = self.algorithm_choice.get()
        purpose = PURPOSES[max(0, self.purpose_choice.current())]
        self._guided_groups = grouped_algorithms(self.catalog, purpose)
        self._group_ids = list(self._guided_groups)
        labels = [group.replace('\\', '/').rsplit('/', 1)[-1] if len(self._guided_groups[group]) > 1
                  else self._algorithm_label(self._guided_groups[group][0]) for group in self._group_ids]
        self.algorithm_choice.configure(values=labels)
        if labels:
            self.algorithm_choice.current(labels.index(previous) if previous in labels else 0)
        else:
            self.algorithm_choice.set('')
        self._select_algorithm()

    def _select_algorithm(self):
        previous = self.variant_choice.current()
        old = self._guided_ids[previous] if 0 <= previous < len(self._guided_ids) else None
        index = self.algorithm_choice.current()
        self._guided_ids = self._guided_groups[self._group_ids[index]] if 0 <= index < len(self._group_ids) else []
        self.variant_choice.configure(values=[self._algorithm_label(name) for name in self._guided_ids])
        if self._guided_ids:
            self.variant_choice.current(self._guided_ids.index(old) if old in self._guided_ids else 0)
        else:
            self.variant_choice.set('')
        if len(self._guided_ids) > 1:
            self.variant_box.pack(fill='x', before=self.guided_help_widget)
        else:
            self.variant_box.pack_forget()
        self._describe_guided()

    def _describe_guided(self):
        index = self.variant_choice.current()
        name = self._guided_ids[index] if 0 <= index < len(self._guided_ids) else None
        issue, blocked = choice_issue(name, self.catalog, self.config['effects'], replacing=self._replace_index)
        target = (tr('realtime.workflow.replacing', index=self._replace_index + 1) + '\n'
                  if self._replace_index is not None else '')
        self.guided_help.set(target + effect_description(name, brief=True) + '\n' + issue if name else tr('realtime.effects.empty'))
        self.guided_help_widget.set_details(effect_description(name) + '\n' + issue if name else tr('realtime.effects.choose_hint'))
        self.guided_add.configure(state='disabled' if not name or blocked else 'normal',
                                 text=tr('realtime.workflow.replace' if self._replace_index is not None else 'realtime.workflow.add_step'))
        if self._replace_index is not None:
            self.cancel_replace.pack(side='right', padx=(4, 0))
        else:
            self.cancel_replace.pack_forget()

    def _add_guided(self):
        index = self.variant_choice.current()
        if 0 <= index < len(self._guided_ids):
            self._insert_effect(self._guided_ids[index])

    def _insert_effect(self, name):
        try:
            effects = self.collect()['effects']
            issue, blocked = choice_issue(name, self.catalog, effects, replacing=self._replace_index)
            if blocked:
                self.status.set(issue)
                return
            index = self._replace_index
            if index is not None:
                if effects[index]['name'] != name:
                    replacement = new_effect(name)
                    replacement.update(scaling_type=effects[index].get('scaling_type', 0), scale=effects[index].get('scale', [1, 1]))
                    effects[index] = replacement
            else:
                index = len(effects)
                effects.append(new_effect(name))
            self._commit_effects(effects, index)
            self._cancel_replacement()
        except ValueError as error:
            self.status.set(str(error))

    def _choose_replacement(self):
        selection = self.chain.curselection()
        if not selection:
            return
        self._replace_index = selection[0]
        name = self.config['effects'][selection[0]]['name']
        self.purpose_choice.current(PURPOSES.index(effect_category(name)))
        self._refresh_guided()
        group = algorithm_group(name)
        if group in self._group_ids:
            self.algorithm_choice.current(self._group_ids.index(group))
            self._select_algorithm()
            if name in self._guided_ids:
                self.variant_choice.current(self._guided_ids.index(name))
        if self.add_section.collapsed:
            self.add_section.toggle()
        self._describe_guided()
        self._describe_effect_choice()
        self._focus_page('effects', self.purpose_choice)

    def _cancel_replacement(self):
        self._replace_index = None
        self._describe_guided()
        self._describe_effect_choice()

    def _focus_parameters(self):
        self._focus_page('effects', self.parameter_frame)

    def _toggle_favorite(self):
        index = self.effect_choice.current()
        if not 0 <= index < len(self._effect_ids):
            return
        name = self._effect_ids[index]
        favorites = list(self.store.data.get('effect_favorites', []))
        if name in favorites:
            favorites.remove(name)
        else:
            favorites.append(name)
        try:
            self.store.save_effect_favorites(favorites)
            self._filter_effects()
        except (OSError, ValueError) as error:
            self.status.set(str(error))

    def _scroll_page(self, tabs, title):
        page = ttk.Frame(tabs.content, style='Panel.TFrame')
        tabs.add(page, text=title)
        return self._scroll_content(page)

    def _scroll_content(self, page, *, stage=False):
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        canvas = tk.Canvas(page, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(page, orient='vertical', command=canvas.yview)
        canvas.grid(row=0, column=0, sticky='nsew')
        bar.grid(row=0, column=1, sticky='ns')
        bar.grid_remove()
        canvas.configure(yscrollcommand=bar.set)
        content = ttk.Frame(canvas, padding=12, style='Stage.TFrame' if stage else 'Panel.TFrame')
        item = canvas.create_window((0, 0), window=content, anchor='nw')

        def sync(_=None):
            height = content.winfo_reqheight()
            viewport = canvas.winfo_height()
            if viewport < 2:
                return
            overflow = height > viewport
            if overflow and not bar.winfo_manager():
                bar.grid()
            elif not overflow and bar.winfo_manager():
                bar.grid_remove()
            # A region shorter than the viewport lets Tk retain a negative
            # origin after resizing/scrolling, leaving empty space at the top.
            canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), max(height, viewport)))
            if not overflow:
                canvas.yview_moveto(0)

        def resize(event):
            canvas.itemconfigure(item, width=event.width)
            sync()

        content.bind('<Configure>', sync)
        canvas.bind('<Configure>', resize)
        self._scroll_canvases[page] = canvas
        self._scroll_bars[page] = bar
        return content

    def _label(self, parent, text='', *, variable=None, muted=False, font=None):
        stage = str(parent.cget('style')) == 'Stage.TFrame'
        style = ('RealtimeStageMuted.TLabel' if muted else 'RealtimeStage.TLabel') if stage else ('Hint.TLabel' if muted else 'TLabel')
        label = ttk.Label(parent, text=text, textvariable=variable, font=font or ui_theme.UI_FONT,
                          style=style, wraplength=260, justify='left')
        label.pack(fill='x', pady=3)
        label.bind('<Configure>', lambda e: label.configure(wraplength=max(40, e.width - 4)))
        return label

    def _button(self, parent, text, command, variant='default', *, icon='', icon_only=False):
        button = ChromeButton(parent, text=text, command=command, variant=variant, ui=self._ui,
                              icon=icon, icon_only=icon_only)
        self._theme_widgets.append(button)
        return button

    def _hint(self, parent, short, details, *, variable=None, parameter=False, heading=False):
        widget = InlineHelp(parent, short, details, ui=self._ui, variable=variable, heading=heading)
        widget.pack(fill='x', pady=3)
        (self._parameter_widgets if parameter else self._theme_widgets).append(widget)
        return widget

    def _hover_help(self, widget, details):
        tip = HoverHelp(widget, details)
        self._theme_widgets.append(tip)
        return tip

    def _combo(self, parent, **options):
        widget = InspectorChoice(parent, ui=self._ui, **options)
        self._theme_widgets.append(widget)
        return widget

    def _entry_field(self, parent, **options):
        widget = ChromeEntry(parent, ui=self._ui, **options)
        self._theme_widgets.append(widget)
        return widget

    def _check(self, parent, text, variable, command=None):
        widget = CheckToggle(parent, text, variable, command=command, ui=self._ui)
        self._theme_widgets.append(widget)
        return widget

    def apply_theme(self, ui):
        self._ui = dict(ui)
        self._paint_splitter()
        style = ttk.Style(self.window)
        style.configure('RealtimeStage.TLabel', background=ui['canvas'], foreground=ui['text'])
        style.configure('RealtimeStageMuted.TLabel', background=ui['canvas'], foreground=ui['muted'])
        for canvas in self._scroll_canvases.values():
            canvas.configure(bg=ui['canvas'] if canvas is self.stage_canvas else ui['panel'])
        stage_ui = dict(ui, panel=ui['canvas'])
        for widget in self._theme_widgets + self._parameter_widgets:
            cursor = widget.widget if isinstance(widget, HoverHelp) else widget
            on_stage = False
            while cursor is not None:
                if cursor is self.stage:
                    on_stage = True
                    break
                cursor = getattr(cursor, 'master', None)
            widget.apply_theme(stage_ui if on_stage else ui)
            if on_stage and isinstance(widget, CollapsibleSection):
                widget.configure(style='Stage.TFrame')
                widget.body.configure(style='Stage.TFrame')
        for widget in (self.regions,):
            widget.configure(bg=ui['entry_bg'], fg=ui['text'], selectbackground=ui['select_bg'],
                             selectforeground=ui['text'], relief='flat', borderwidth=0,
                             highlightthickness=1, highlightbackground=ui['line'])
        self.regions.configure(insertbackground=ui['text'])
        self.log.configure(bg=ui['log_bg'], fg=ui['log_fg'], insertbackground=ui['text'],
                           selectbackground=ui['select_bg'], selectforeground=ui['text'],
                           relief='flat', borderwidth=0, highlightthickness=0)
        self.region_preview.configure(bg=ui['canvas'])
        self._draw_regions()

    def on_mousewheel(self, event):
        cursor = getattr(event, 'widget', None)
        delta = getattr(event, 'delta', 0)
        if self._closed or not delta:
            return None
        try:
            # Tcl-owned combobox popdowns have no Python widget wrapper; Tk
            # delivers their path as a string. Leave their class binding alone.
            if isinstance(cursor, str):
                cursor = self.window.nametowidget(cursor)
            if cursor is None or cursor.winfo_class() in ('Text', 'Listbox', 'TCombobox', 'TSpinbox'):
                return None
            while cursor is not None:
                canvas = self._scroll_canvases.get(cursor)
                if canvas is not None:
                    bounds = canvas.bbox('all')
                    if bounds and bounds[3] - bounds[1] > canvas.winfo_height():
                        canvas.yview_scroll(-3 if delta > 0 else 3, 'units')
                    return 'break'
                cursor = getattr(cursor, 'master', None)
        except (KeyError, tk.TclError):
            # A popdown or a widget destroyed during a mode switch is not an
            # inspector scroll target. Do not consume its native wheel event.
            return None

    def _region_bounds(self):
        return max(1, self.region_preview.winfo_width()), max(1, self.region_preview.winfo_height())

    def _draw_regions(self):
        if not hasattr(self, 'regions'):
            return
        width, height = self._region_bounds()
        self.region_preview.delete('all')
        self.region_preview.create_text(width / 2, height / 2, text=tr("realtime.diagram"),
                                        fill=self._ui['muted'], width=max(40, width-24), font=ui_theme.UI_FONT)
        try:
            regions = [list(map(float, line.split())) for line in self.regions.get('1.0', 'end').splitlines() if line.strip()]
            for i, (x0, y0, x1, y1) in enumerate(regions):
                if not 0 <= x0 < x1 <= 1 or not 0 <= y0 < y1 <= 1:
                    continue
                self.region_preview.create_rectangle(x0*width, y0*height, x1*width, y1*height, outline=self._ui['accent'], width=2)
                self.region_preview.create_text(x0*width+8, y0*height+8, text=str(i+1), anchor='nw', fill=self._ui['accent'])
        except (ValueError, OverflowError):
            pass  # Partial text edits are not applied until validation succeeds.

    def _region_begin(self, event):
        width, height = self._region_bounds()
        self._drag_start = (max(0, min(width, event.x)), max(0, min(height, event.y)))

    def _region_drag(self, event):
        if self._drag_start:
            width, height = self._region_bounds()
            self.region_preview.delete('drag')
            self.region_preview.create_rectangle(*self._drag_start, max(0, min(width, event.x)), max(0, min(height, event.y)), outline=self._ui['accent'], tags='drag')

    def _region_end(self, event):
        if not self._drag_start:
            return
        x, y = self._drag_start; self._drag_start = None
        width, height = self._region_bounds()
        right, bottom = max(0, min(width, event.x)), max(0, min(height, event.y))
        if abs(x-right) < 2 or abs(y-bottom) < 2:
            return
        lines = [line for line in self.regions.get('1.0', 'end').splitlines() if line.strip()]
        if len(lines) >= 4:
            self.status.set(tr("realtime.regions_limit")); return
        lines.append(f'{min(x,right)/width:.4f} {min(y,bottom)/height:.4f} {max(x,right)/width:.4f} {max(y,bottom)/height:.4f}')
        self.regions.delete('1.0', 'end'); self.regions.insert('1.0', '\n'.join(lines))
        self.quality_controls['protection'].set(True)
        self.apply_quality()

    def apply_profile(self, name):
        try:
            self.apply_config(performance_profile(self.collect(), name))
            self.status.set(tr("realtime.profile_loaded"))
        except Exception as error:
            self.status.set(str(error))

    def _choice(self, parent, label, key, values):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        self._label(row, label)
        box = self._combo(row, values=values, state="readonly", width=12)
        box.current(self.config[key])
        box.pack(fill='x')
        self.controls[key] = (box, "choice")
        box.bind('<<ComboboxSelected>>', lambda _: self._editor_changed())

    def _entry(self, parent, label, key):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        self._label(row, label)
        var = tk.StringVar(value=str(self.config[key]))
        field = self._entry_field(row, textvariable=var, width=12)
        field.pack(fill='x')
        self._display_targets[key] = field
        self.controls[key] = (var, "text")
        var.trace_add('write', lambda *_: self._editor_changed())

    def _sync_output_controls(self):
        """Reflect a validated preset or draft without applying it to a session."""
        windowed = self.output_mode.get()
        self._display_targets['game_mode'].configure(state='disabled' if windowed else 'normal')
        self._display_targets['window_scale'].configure(state='normal' if windowed else 'disabled')
        self.output_hint.set(tr('realtime.output.windowed_hint' if windowed else 'realtime.output.fullscreen_hint'))
        self.output_summary.set(tr('realtime.layout.output_draft',
                                  mode=tr('realtime.output.windowed' if windowed else 'realtime.output.fullscreen')))

    def _output_changed(self):
        if self._editor_building or self._closed:
            return
        adjustments = []
        if self.output_mode.get():
            if self.controls['capture_method'][0].current() == 1:
                self.controls['capture_method'][0].current(0)
                adjustments.append(tr('realtime.output.adjust_capture'))
            if self.controls['game_mode'][0].get():
                self.controls['game_mode'][0].set(False)
                adjustments.append(tr('realtime.output.adjust_mouse'))
        self._sync_output_controls()
        if adjustments:
            self.output_hint.set(tr('realtime.output.adjusted', changes=tr('realtime.output.separator').join(adjustments)))
        # Only edit the draft. In particular, never auto-switch to fullscreen
        # or restart a running capture when resolving an incompatible option.
        self._editor_changed()

    def _pick_monitor(self, _=None):
        index = self.monitor_picker.current()
        if index >= 0:
            self.controls['monitor_id'][0].set(self._monitors[index]['id'])
            self.controls['monitor_mode'][0].current(3)

    def _pick_gpu(self, _=None):
        index = self.gpu_picker.current()
        self.controls['gpu_index'][0].set(-1 if index == 0 else self._adapters[index-1]['index'])

    def select_runtime(self):
        if self.session_summary()[1]:
            self.status.set(tr("realtime.stop_before_runtime"))
            return
        directory = filedialog.askdirectory(parent=self.window, title=tr("realtime.runtime_title"))
        if directory:
            self.client.close()
            self.store.save_runtime_directory(directory)
            self.client.settings['realtime_runtime_directory'] = directory
            self.client.send('devices')
            self.status.set(tr("realtime.runtime_changed"))

    def export_diagnostics(self):
        if self._on_export_diagnostics is not None:
            return self._on_export_diagnostics()
        if self._diagnosing:
            return
        filename = filedialog.asksaveasfilename(parent=self.window, title=tr('dialog.save_diagnostics'),
                    initialfile=support_diagnostics.suggested_name('realtime'), defaultextension='.log',
                    filetypes=[(tr('filetype.diagnostic'), '*.log'), ('JSON', '*.json')])
        if not filename:
            return
        context = {'workbench_mode': 'realtime', 'settings': dict(self.client.settings),
                   'realtime': self.diagnostic_snapshot(),
                   '_diagnostic_io': {'realtime_logs': str(paths.state_path('realtime') / 'logs')}}
        self._diagnosing = True
        result_queue = queue.Queue()
        def worker():
            try:
                result = support_diagnostics.write_report(filename, context)
                result_queue.put((result, None))
            except Exception as error:
                result_queue.put((None, str(error)))
        def finish():
            if self._closed:
                return
            try:
                result, error = result_queue.get_nowait()
            except queue.Empty:
                self._diagnostic_after = self.window.after(100, finish)
                return
            self._diagnostic_after = None
            self._diagnosing = False
            if error:
                self.status.set(tr('diagnostics.failed', error=error))
                messagebox.showerror(tr('dialog.diagnostics_failed'), error, parent=self.window)
            else:
                self.status.set(tr('diagnostics.saved', path=result['path']))
                messagebox.showinfo(tr('dialog.diagnostics_complete'), tr('message.diagnostics_complete', path=result['path']), parent=self.window)
        self.status.set(tr('diagnostics.started'))
        threading.Thread(target=worker, name='realtime-diagnostic', daemon=True).start()
        self._diagnostic_after = self.window.after(100, finish)

    def _record_status(self, *_):
        self.diagnostics.append({'event': 'ui_status', 'message': self.status.get(), 'run_id': self._run_id})
        self._write_log(self.status.get())
        # Lifecycle already has a dedicated, target-safe summary. Keep errors
        # and actionable notices visible, without repeating normal confirmations.
        label = getattr(self, 'status_label', None)
        if label is not None:
            routine = {tr('realtime.' + key) for key in (
                'not_started', 'running', 'stopped', 'starting', 'stopping',
                'initializing', 'init_wait_output', 'stopping_short', 'output_ready',
                'parameters_saved', 'quality_saved', 'parameters_unchanged')}
            if self.status.get() in routine:
                label.pack_forget()
            elif not label.winfo_manager():
                label.pack(fill='x', pady=3)

    def _write_log(self, message):
        message = compact(message)
        if not message or not hasattr(self, 'log') or message == getattr(self, '_last_log_message', None):
            return
        self._last_log_message = message
        follow_tail = self.log.yview()[1] >= .999
        self.log.configure(state='normal')
        self.log.insert('end', tr('realtime.log.line', message=message) + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 500:
            self.log.delete('1.0', '100.0')
        if follow_tail:
            self.log.see('end')
        self.log.configure(state='disabled')

    def diagnostic_snapshot(self):
        """Read raw drafts without validation, saving or sending commands."""
        selection = getattr(self.client, 'runtime_selection', None)
        return deepcopy({
            'session': {'phase': self.session_summary()[0], 'busy': self.session_summary()[1],
                        'run_id': self._run_id, 'generation': self.client.generation,
                        'render_confirmed': self._render_confirmed, 'target': self._session_target,
                        'selected_target': self.selected_window(), 'recovering': self._recovering},
            'runtime_at_launch': selection if isinstance(selection, dict) else None,
            'runtime_settings': dict(self.client.settings),
            'running_config': self._running_config, 'applied_effects': self._applied_effects,
            'draft_base': self.config,
            'draft_fields': {'effect': self._parameter_snapshot(),
                             'effect_index': next(iter(self.parameters.values()))[0] if self.parameters else None,
                             'display': {key: control.current() if kind == 'choice' else control.get()
                                         for key, (control, kind) in self.controls.items()},
                             'quality': {key: var.get() for key, var in self.quality_controls.items()},
                             'regions': self.regions.get('1.0', 'end')},
            'pending': {'start': self._pending_start, 'quality': self._pending_quality,
                        'parameters': [{'effect': i, 'name': n, 'value': v} for (i, n), v in self._live_expected.items()]},
            'editor': {'state': self._editor_state, 'message': self.editor_status.get(), 'error': self._edit_error},
            'devices': {'monitors': getattr(self, '_monitors', []), 'adapters': getattr(self, '_adapters', [])},
            'metrics': self._last_metrics,
            'catalog': {'total': len(self.catalog), 'available': sum(e.get('available', True) for e in self.catalog.values())},
            'journal': self.diagnostics.snapshot(),
        })

    def collect(self):
        self._store_parameters()
        config = deepcopy(self.config)
        for key, (control, kind) in self.controls.items():
            value = control.current() if kind == "choice" else control.get()
            if key == "gpu_index":
                value = int(value)
            elif key in ("frame_rate", 'window_scale'):
                value = float(value)
            config[key] = value
        config['quality'] = {k: v.get() if k == 'protection' else float(v.get()) for k, v in self.quality_controls.items()}
        config['quality']['regions'] = [[float(v) for v in line.replace(',', ' ').split()] for line in self.regions.get('1.0', 'end').splitlines() if line.strip()]
        return validate_config(config)

    def apply_config(self, config):
        self.config = validate_config(config)
        self._chain_undo = None
        self._replace_index = None
        was_building = self._editor_building
        self._editor_building = True
        self._edit_error = ''
        self._queued_parameter_apply = False
        self._queued_quality_apply = False
        self.parameters = {}
        self.scale_controls = None
        for key, (control, kind) in self.controls.items():
            if kind == "choice":
                control.current(self.config[key])
            else:
                control.set(self.config[key])
        for key, var in self.quality_controls.items():
            var.set(self.config['quality'][key])
        self._sync_output_controls()
        self.regions.delete('1.0', 'end')
        self.regions.insert('1.0', '\n'.join(' '.join(map(str, r)) for r in self.config['quality']['regions']))
        self._render_chain()
        self._draw_regions()
        self._editor_building = was_building
        self._refresh_editor_state()

    def _overlay_draft(self):
        """Read valid fields without rewriting unfinished input in other rows."""
        draft = deepcopy(self.config)
        invalid = set()
        for name, (index, var, integer) in self.parameters.items():
            try:
                row = self.parameter_rows.get(name)
                value = float(row.value() if row else var.get())
                if not math.isfinite(value) or (integer and not value.is_integer()):
                    raise ValueError(name)
                draft['effects'][index].setdefault('parameters', {})[name] = int(value) if integer else value
            except (ValueError, TypeError, tk.TclError):
                invalid.add((index, name))
        if self.parameters:
            index = next(iter(self.parameters.values()))[0]
            effect = draft['effects'][index]
            disabled = set(effect.get('disabled_parameters', [])) - set(self.parameter_toggles)
            disabled.update(n for n, var in self.parameter_toggles.items() if not var.get())
            effect['disabled_parameters'] = sorted(disabled)
            if self.extended_range is not None:
                effect['extended_range'] = self.extended_range.get()
        return draft, invalid

    def _patch_overlay_editor(self, previous, editor):
        """Update values in place, rebasing local undo without rebuilding widgets."""
        was_building = self._editor_building
        self._editor_building = True
        try:
            self.config['effects'] = deepcopy(editor['effects'])
            if self.parameters:
                index = next(iter(self.parameters.values()))[0]
                effect = editor['effects'][index]
                for name, toggle in self.parameter_toggles.items():
                    enabled = name not in effect.get('disabled_parameters', [])
                    if toggle.get() != enabled:
                        toggle.set(enabled)
                        for snapshot in (self._edit_snapshot, self._pending_undo, self._undo_parameters):
                            if snapshot is not None:
                                snapshot.get('toggles', {})[name] = enabled
                if self.extended_range is not None and nr_extended_range(effect) and not self.extended_range.get():
                    self.extended_range.set(True)
                    self._update_range_controls()
                    for snapshot in (self._edit_snapshot, self._pending_undo, self._undo_parameters):
                        if snapshot is not None:
                            snapshot['extended_range'] = True
            for name, (index, var, _) in self.parameters.items():
                old = previous['effects'][index].get('parameters', {}).get(name)
                value = editor['effects'][index].get('parameters', {}).get(name)
                if self._same_parameter(old, value):
                    continue
                var.set(str(value))
                for snapshot in (self._edit_snapshot, self._pending_undo, self._undo_parameters):
                    if snapshot is not None and name in snapshot['parameters']:
                        snapshot['parameters'][name] = str(value)
            for key in ('sync_enabled', 'frame_rate', 'sync_mode'):
                if previous[key] == editor[key]:
                    continue
                control, kind = self.controls[key]
                control.current(editor[key]) if kind == 'choice' else control.set(editor[key])
                self.config[key] = editor[key]
        finally:
            self._editor_building = was_building

    def _receive_overlay_settings(self, events):
        """Persist one consecutive batch; saved values are not applied receipts."""
        ok = conflict = False
        try:
            if (self._running_config is None or self._stop_requested or self._recovering or self._pending_start
                    or any(e.get('run_id') != self._run_id for e in events)):
                raise ValueError(tr('realtime.stale_save'))
            original, invalid = self._overlay_draft()
            editor = deepcopy(original)
            saved = deepcopy(self._running_config)
            if self._overlay_saved:
                saved.update({key: deepcopy(self._overlay_saved[key]) for key in
                              ('effects', 'sync_enabled', 'frame_rate', 'sync_mode')})
            defaults = {name: {p['name']: p['default'] for p in item.get('parameters', [])}
                        for name, item in self.catalog.items()}
            changed = {}
            try:
                for event in events:
                    for index, (before, after) in enumerate(zip(event['previous_effects'], event['effects'])):
                        for name, value in after.get('parameters', {}).items():
                            old = before.get('parameters', {}).get(name, defaults.get(before['name'], {}).get(name))
                            if not self._same_parameter(old, value):
                                if (index, name) in invalid:
                                    raise ValueError(tr('realtime.error.parameter_conflict', field=name))
                                changed[index, name] = value
                    merged = merge_overlay_effects(effective_nr_skin(editor), event['previous_effects'],
                                                   event['effects'], defaults)
                    editor = restore_nr_skin_memory(merged, editor)
                    # Older hosts do not send previousFrameSync. The last native
                    # save (not the local display draft) is its merge baseline.
                    for key in ('sync_enabled', 'frame_rate', 'sync_mode'):
                        if event[key] == saved[key]:
                            continue
                        control, kind = self.controls[key]
                        raw = control.current() if kind == 'choice' else control.get()
                        current = editor[key] if key in changed else raw
                        if not (self._same_parameter(current, saved[key]) or self._same_parameter(current, event[key])):
                            raise ValueError(tr('realtime.error.parameter_conflict', field=tr('realtime.' + key)))
                        editor[key] = event[key]
                        changed[key] = event[key]
                    saved.update({k: deepcopy(event[k]) for k in ('effects', 'sync_enabled', 'frame_rate', 'sync_mode')})
            except (ValueError, TypeError, KeyError):
                conflict = True
                raise
            saved = validate_config(restore_nr_skin_memory(saved, editor))
            self.store.save_session(saved)
            self._overlay_saved = deepcopy(saved)
            self._patch_overlay_editor(original, editor)
            for key, value in changed.items():
                if isinstance(key, tuple) and self._parameter_modes.get(key) == 1:
                    self._overlay_expected[key] = value
            if self._overlay_expected:
                self._overlay_sent_at = time.monotonic()
            ok = True
            self._write_log(tr('realtime.log.settings_saved'))
        except Exception as error:
            self.status.set(str(error))
        for event in events:
            self.client.send('save_result', token=event['token'], ok=ok, conflict=conflict)
        if ok:
            # Ask for an applied snapshot now, not after the next 1s metrics tick.
            self.client.send('status')
            self._last_status_request = time.monotonic()

    def _event_batches(self):
        # Consume lazily: recovery may break the poll loop, and must still see
        # queued emergency-stop/lifecycle events instead of losing a drained tail.
        remaining = 50
        while remaining:
            try:
                event = self.client.events.get_nowait()
            except queue.Empty:
                return
            remaining -= 1
            batch = [event]
            while remaining and event.get('event') == 'settings_requested':
                # Tk is the sole consumer. Peek under Queue's lock so we never
                # dequeue a lifecycle barrier just to discover it is not a save.
                with self.client.events.mutex:
                    queued = self.client.events.queue
                    same = bool(queued) and all(event.get(k) == queued[0].get(k)
                                               for k in ('event', 'run_id', '_generation'))
                if not same:
                    break
                batch.append(self.client.events.get_nowait())
                remaining -= 1
            yield batch

    def _confirm_overlay_parameters(self, event):
        if not self._overlay_expected:
            return
        pending = {}
        for (index, name), value in self._overlay_expected.items():
            actual = None
            if index < len(self._applied_effects):
                effect = self._applied_effects[index]
                default = next((p['default'] for p in self.catalog.get(effect['name'], {}).get('parameters', [])
                                if p['name'] == name), None)
                actual = effect.get('parameters', {}).get(name, default)
            if not self._same_parameter(actual, value):
                pending[index, name] = value
        self._overlay_expected = pending
        if not pending and self._running_config:
            self._running_config['effects'] = deepcopy(self._applied_effects)
            if self._known_good:
                self._known_good = (self._known_good[0], restore_nr_skin_memory(self._running_config, self.config))
        elif event.get('apply_failed'):
            self._overlay_expected.clear()
            self._edit_error = tr('realtime.editor.overlay_failed')

    def _refresh_metrics_summary(self):
        busy = self.session_summary()[1]
        if not self._metrics_compact:
            text = tr('realtime.metrics_wait' if busy else 'realtime.metrics_idle')
        elif (not busy or self._pending_start or self._stop_requested or not self._render_confirmed
              or self._native_state == 4 or (self._metrics_run_id is not None and self._metrics_run_id != self._run_id)):
            text = tr('realtime.metrics_previous', value=self._metrics_compact)
        else:
            text = self._metrics_compact
        if self.metrics_summary.get() != text:
            self.metrics_summary.set(text)

    def apply_quality(self):
        try:
            config = self.collect()
            self._draw_regions()
            self.config['quality'] = config['quality']
            if self._target_differs():
                # This is the pending source's draft, not the old session.
                self._refresh_editor_state()
                return
            if self._active:
                if not any(e['name'] == DEFAULT_CONFIG['effects'][0]['name'] for e in (self._running_config or {}).get('effects', [])):
                    raise ValueError(tr("realtime.quality_no_nr"))
                command = self.client.send('quality', quality=config['quality'], run_id=self._run_id)
                self._pending_quality = {'command': command, 'quality': deepcopy(config['quality']),
                                         'revision': None, 'run_id': self._run_id, 'sent_at': time.monotonic()}
                self.status.set(tr("realtime.quality_pending"))
            else:
                self.store.save_session(config)
        except Exception as error:
            self._edit_error = str(error)
            self.status.set(str(error))
        self._refresh_editor_state()

    def refresh(self):
        try:
            previous = self.selected_window()
            self.windows = list_windows()
            self.target.configure(values=[f"{w['title']}  · PID {w['pid']}" for w in self.windows])
            index = next((i for i, w in enumerate(self.windows) if previous and
                          (w['hwnd'], w['pid']) == (previous['hwnd'], previous['pid'])), None)
            if index is not None:
                self.target.current(index)
            else:
                self.target.set('')
                if previous:
                    self.status.set(tr("realtime.target_closed"))
        except Exception as error:
            self.status.set(str(error))

    def selected_window(self):
        index = self.target.current()
        return self.windows[index] if 0 <= index < len(self.windows) else None

    def _target_changed(self, _=None):
        selected = self.selected_window()
        config = self.store.for_application(selected["application"]) if selected else None
        if config:
            self.apply_config(config)
        self._notify_session()

    def _render_chain(self, index=0):
        self.chain.set_items([(step_title(effect['name']), step_subtitle(effect, self.catalog))
                              for effect in self.config['effects']], index)
        self._select_effect()
        self._refresh_workflow()

    def _filter_effects(self):
        previous = self.effect_choice.current()
        selected = self._effect_ids[previous] if 0 <= previous < len(self._effect_ids) else None
        query = self.effect_search.get().strip().casefold()
        category = EFFECT_CATEGORIES[max(0, self.effect_category.current())]
        favorites = self.store.data.get('effect_favorites', [])
        self._effect_ids = sorted(name for name, item in self.catalog.items()
                                  if (not self.favorites_only.get() or name in favorites)
                                  and (category == 'all' or effect_category(name) == category)
                                  and query in (name + ' ' + effect_title(name, item) + ' ' +
                                                tr('realtime.effects.category.' + effect_category(name)) + ' ' +
                                                effect_description(name)).casefold())
        # The path disambiguates identically named third-party effects.
        labels = [('★ ' if name in favorites else '') + f'{self._algorithm_label(name)}  ·  {name}' for name in self._effect_ids]
        self.effect_choice.configure(values=labels)
        if self._effect_ids:
            self.effect_choice.current(self._effect_ids.index(selected) if selected in self._effect_ids else 0)
        else:
            self.effect_choice.set('')
        self.effect_count.set(tr('realtime.effects.count', shown=len(self._effect_ids), total=len(self.catalog),
                                 unavailable=sum(not item.get('available', True) for item in self.catalog.values())))
        self._describe_effect_choice()

    def _describe_effect_choice(self):
        index = self.effect_choice.current()
        name = self._effect_ids[index] if 0 <= index < len(self._effect_ids) else None
        issue, blocked = choice_issue(name, self.catalog, self.config['effects'], replacing=self._replace_index)
        self.library_add.configure(state='disabled' if not name or blocked else 'normal',
                                   text=tr('realtime.workflow.replace') if self._replace_index is not None else tr('realtime.editor.add'))
        self.favorite_button.configure(state='normal' if name else 'disabled',
            text=tr('realtime.workflow.unfavorite' if name in self.store.data.get('effect_favorites', []) else 'realtime.workflow.favorite'))
        if 0 <= index < len(self._effect_ids):
            self.effect_help.set(effect_description(name, brief=True) + '\n' + issue)
            self.effect_help_widget.set_details(effect_description(name) + '\n' + issue + '\n' + tr('realtime.effects.availability'))
        else:
            self.effect_help.set(tr('realtime.effects.empty'))
            self.effect_help_widget.set_details(tr('realtime.effects.choose_hint'))

    def _store_parameters(self):
        for name, (index, var, integer) in self.parameters.items():
            row = self.parameter_rows.get(name)
            value = float(row.value() if row is not None else var.get())
            if integer and not value.is_integer():
                raise ValueError(tr('realtime.integer_required', name=name))
            self.config["effects"][index].setdefault("parameters", {})[name] = int(value) if integer else value
        if self.parameters:
            index = next(iter(self.parameters.values()))[0]
            effect = self.config['effects'][index]
            if self.extended_range is not None and self._range_index == index:
                if self.extended_range.get():
                    effect['extended_range'] = True
                else:
                    effect.pop('extended_range', None)
            disabled = set(effect.get('disabled_parameters', [])) - set(self.parameter_toggles)
            disabled.update(name for name, var in self.parameter_toggles.items() if not var.get())
            if disabled:
                effect['disabled_parameters'] = sorted(disabled)
            else:
                effect.pop('disabled_parameters', None)
        if self.scale_controls:
            index, kind, x, y = self.scale_controls
            self.config['effects'][index]['scaling_type'] = kind.current()
            self.config['effects'][index]['scale'] = [float(x.get()), float(y.get())]

    def _select_effect(self, _=None):
        try:
            self._store_parameters()
        except ValueError as error:
            self.status.set(tr('realtime.invalid_parameter', error=error))
            previous = next(iter(self.parameters.values()), None)
            if previous is not None:
                self.chain.selection_clear(0, 'end')
                self.chain.selection_set(previous[0])
            self._refresh_editor_state()
            return
        self.parameters = {}
        self.scale_controls = None
        self.parameter_rows = {}
        self.parameter_sections = {}
        self.pass_toggles = {}
        self.skin_pairs = {}
        self.parameter_toggles = {}
        self.extended_range = None
        self._range_index = None
        self._parameter_groups = {}
        self._pending_undo = self._undo_parameters = self._edit_snapshot = None
        self._parameter_widgets = []
        for child in self.parameter_frame.winfo_children():
            child.destroy()
        selection = self.chain.curselection()
        if not selection:
            return
        if self._replace_index is not None and self._replace_index != selection[0]:
            self._cancel_replacement()
        was_building = self._editor_building
        self._editor_building = True
        index = selection[0]
        effect = self.config["effects"][index]
        desc = self.catalog.get(effect["name"], {})
        self.parameter_heading.label.configure(text=effect_title(effect['name'], desc))
        self.parameter_heading.set_details(effect_description(effect['name']) + '\n' + tr('realtime.editor.effect_hint'))
        variants = grouped_algorithms(self.catalog, effect_category(effect['name'])).get(algorithm_group(effect['name']), [])
        if len(variants) > 1:
            self._label(self.parameter_frame, tr('realtime.workflow.variant'), muted=True)
            choice = InspectorChoice(self.parameter_frame, state='readonly', width=12, ui=self._ui,
                                     values=[self._algorithm_label(name) for name in variants])
            choice.current(variants.index(effect['name']))
            choice.pack(fill='x')
            self._parameter_widgets.append(choice)
            self._hint(self.parameter_frame, tr('realtime.workflow.variant'), tr('realtime.workflow.variant_hint'), parameter=True)
            def change_variant(_=None):
                name = variants[choice.current()]
                self._replace_index = index
                self._insert_effect(name)
                self._replace_index = None
                # Invalid drafts and unsupported variants must not masquerade
                # as a successful replacement in the still-existing selector.
                if choice.winfo_exists():
                    choice.current(variants.index(self.config['effects'][index]['name']))
                self._describe_guided()
                self._describe_effect_choice()
            choice.bind('<<ComboboxSelected>>', change_variant)
        groups = inspector_groups(effect['name'], desc.get('parameters', []))
        is_nr = effect['name'].replace('/', '\\') == NR
        names = {p['name'] for p in desc.get('parameters', [])}
        if is_nr:
            self.skin_pairs = {strength: mask for strength, mask in NR_SKIN_PAIRS
                               if strength in names and mask in names}
            ranged = [p for p in desc.get('parameters', []) if p['name'] in NR_RANGE_PARAMETERS
                      and not p['integer'] and p['max'] > 1 and p['min'] == 0]
            if ranged:
                loaded = dict(effect, parameters={p['name']: effect.get('parameters', {}).get(p['name'], p['default'])
                                                  for p in ranged})
                self.extended_range = tk.BooleanVar(self.window, value=nr_extended_range(loaded))
                self._range_index = index
        has_pass_switches = (effect['name'].replace('/', '\\') == NR
                            and any(p['name'] == 'multiPass' for p in desc.get('parameters', []))
                            and all(any(key == 'pass' + str(n) for key, _, _ in groups) for n in (2, 3)))
        if not any(key == 'resolution' for key, _, _ in groups):
            groups.append(('resolution', tr('realtime.editor.group.resolution'), []))
        more = CollapsibleSection(self.parameter_frame, tr('realtime.layout.more_parameters'),
                                  collapsed=not self._section_open.get((effect['name'], 'more'), False), ui=self._ui)
        more._on_toggle = lambda: self._section_open.__setitem__((effect['name'], 'more'), not more.collapsed)
        self._parameter_widgets.append(more)
        for number, (key, title, items) in enumerate(groups):
            section_key = (effect['name'], key)
            expanded = self._section_open.get(section_key, key == 'look' or (number == 0 and key.startswith('native:')))
            primary = key == 'look' or (number == 0 and key.startswith('native:'))
            section = InspectorSection(self.parameter_frame if primary else more.body, title, collapsed=not expanded, ui=self._ui)
            Tooltip(section._header, tr('realtime.editor.group_count_hint'))
            section._on_toggle = lambda k=section_key, s=section: self._section_open.__setitem__(k, not s.collapsed)
            section.pack(fill='x', pady=(8, 0))
            self.parameter_sections[key] = section
            self._parameter_groups[key] = (title, [item['name'] for item in items
                                                  if item['name'] != 'multiPass' or not has_pass_switches])
            self._parameter_widgets.append(section)
            if key == 'look' and self.extended_range is not None:
                maximum = max(p['max'] for p in ranged)
                self.range_toggle = CheckToggle(section.body,
                    tr('parameter.range_toggle', maximum=f'{maximum:.2f}'), self.extended_range,
                    command=self._toggle_extended_range, ui=self._ui)
                self.range_toggle.pack(anchor='w', pady=(4, 4))
                Tooltip(self.range_toggle, tr('parameter.realtime_range_hint'))
                self._parameter_widgets.append(self.range_toggle)
            if key in ('pass2', 'pass3') and has_pass_switches:
                count = int(key[-1])
                enabled = tk.BooleanVar(self.window, value=False)
                toggle = section.add_enable_toggle(enabled, lambda n=count: self._toggle_pass(n),
                                                   tr('realtime.editor.pass_toggle_hint', count=count))
                self.pass_toggles[count] = (enabled, toggle)
                self._parameter_widgets.append(toggle)
                self._hint(section.body, tr('realtime.help.pass'), tr('realtime.editor.pass_hint'), parameter=True)
            if key == 'resolution':
                self._build_scale(section.body, index, effect)
            # Register both native fields before constructing their shared row;
            # metadata may put the automatic-mask field before the strength.
            for item in items:
                var = tk.StringVar(self.window, value=str(effect.get('parameters', {}).get(item['name'], item['default'])))
                self.parameters[item['name']] = (index, var, item['integer'])
            for item in items:
                var = self.parameters[item['name']][1]
                mask = self.skin_pairs.get(item['name'])
                enabled_var = self.parameters[mask][1] if mask else None
                if is_nr and item['name'] in NR_SWITCH_PARAMETERS:
                    enabled_var = tk.BooleanVar(self.window, value=item['name'] not in effect.get('disabled_parameters', []))
                    self.parameter_toggles[item['name']] = enabled_var
                choices = None
                style = effect['name'].replace('/', '\\') == 'DLSSNR\\DLSSNR_AI_Filter' and item['name'] in ('style', 'pass2_style', 'pass3_style')
                if style and not item.get('choices') and item['min'] == 0 and item['max'] == 2:
                    choices = [(0, tr('style.default')), (1, tr('style.natural')), (2, tr('style.cinema'))]
                row = ParameterRow(section.body, item, var, ui=self._ui, choices=choices, chips=style,
                                   on_commit=self._parameter_committed, on_change=self._editor_changed,
                                   on_reset=lambda name=item['name'], paired=mask: self._reset_parameters([name, paired] if paired else [name]),
                                   label=tr('label.skin_mask') if mask else None,
                                   hint=parameter_hint(item['name']) if is_nr else '',
                                   enabled_variable=enabled_var, allow_percent=is_nr and not item['integer'],
                                   range_hint=is_nr and item['name'] in NR_RANGE_PARAMETERS)
                if self.extended_range is not None and item['name'] in NR_RANGE_PARAMETERS:
                    row.set_maximum(item['max'] if self.extended_range.get() else min(1, item['max']))
                # The native count stays in the model, but its UI is the two
                # explicit pass switches, not a second ambiguous selector.
                if (item['name'] != 'multiPass' or not has_pass_switches) and item['name'] not in self.skin_pairs.values():
                    row.pack(fill='x', pady=(4, 8))
                self._parameter_widgets.append(row)
                self.parameter_rows[item['name']] = row
            reset = ChromeButton(section.body, text=tr('realtime.editor.reset_group'), variant='tool', ui=self._ui,
                                 command=lambda k=key: self._reset_parameters(self._parameter_groups[k][1], scale=k == 'resolution'))
            reset.pack(anchor='e', pady=(4, 0))
            self._parameter_widgets.append(reset)
        more.pack(fill='x', pady=(8, 0))
        self._edit_snapshot = self._parameter_snapshot()
        self._editor_building = was_building
        self._refresh_editor_state()

    def _update_range_controls(self):
        if self.extended_range is not None:
            for name, row in self.parameter_rows.items():
                if name in NR_RANGE_PARAMETERS:
                    row.set_maximum(row.descriptor['max'] if self.extended_range.get() else min(1, row.descriptor['max']))

    def _toggle_extended_range(self):
        if not self.extended_range.get():
            blocked = []
            for name, row in self.parameter_rows.items():
                if name not in NR_RANGE_PARAMETERS:
                    continue
                try:
                    if not 0 <= parse_number(row.variable.get(), percent=True) <= 1:
                        blocked.append(row.title)
                except (ValueError, TypeError, tk.TclError):
                    blocked.append(row.title)
            if blocked:
                self.extended_range.set(True)
                messagebox.showwarning(tr('parameter.range_title'),
                    tr('parameter.range_blocked', names='、'.join(blocked)), parent=self.window)
                return
        self._update_range_controls()
        # Range is UI-only; never submit a previously unfinished numeric edit.
        self._refresh_editor_state()
        if self._running_config is not None:
            try:
                self._save_running_session()
            except Exception as error:
                self.status.set(tr('realtime.save_after_output_failed', error=error))

    def _toggle_pass(self, count):
        current = self.parameter_rows['multiPass'].value()
        requested = self.pass_toggles[count][0].get()
        if count == 3 and requested and current < 2:
            self._refresh_parameter_feedback()
            return
        self.parameters['multiPass'][1].set(str(max(current, count) if requested else count - 1))
        # Uses the same undo / live acknowledgement / explicit restart path as
        # every parameter. Switching off never discards later-pass settings.
        if requested:
            section = self.parameter_sections['pass' + str(count)]
            if section.collapsed:
                section.toggle()
        self._parameter_committed()

    def _build_scale(self, parent, index, effect):
        self._label(parent, tr('realtime.editor.scale_mode'), muted=True)
        kind = InspectorChoice(parent, values=[tr('realtime.scale.factor'), tr('realtime.scale.fit'),
                                tr('realtime.scale.absolute'), tr('realtime.scale.fill')], state='readonly', width=12, ui=self._ui)
        kind.current(effect.get('scaling_type', 0))
        kind.pack(fill='x', pady=(0, 6))
        self._parameter_widgets.append(kind)
        x, y = (tk.StringVar(self.window, value=str(v)) for v in effect.get('scale', [1, 1]))
        self.scale_controls = (index, kind, x, y)
        labels, fields = [], []
        for var in (x, y):
            row = ttk.Frame(parent, style='Panel.TFrame')
            row.pack(fill='x', pady=3)
            field = ChromeEntry(row, textvariable=var, width=8, ui=self._ui)
            field.pack(side='right')
            label = ttk.Label(row, style='TLabel')
            label.pack(side='left')
            labels.append(label); fields.append(field)
            self._parameter_widgets.append(field)
            var.trace_add('write', lambda *_: self._editor_changed())
        def update_units(_=None):
            absolute = kind.current() == 2
            for axis, label, field in zip(('width', 'height'), labels, fields):
                label.configure(text=tr('realtime.editor.' + axis + ('_px' if absolute else '_factor')))
                field.configure(state='disabled' if kind.current() in (1, 3) else 'normal')
            self._editor_changed()
        kind.bind('<<ComboboxSelected>>', update_units)
        self._update_scale_units = update_units
        update_units()

    def _add(self):
        selected = self.effect_choice.current()
        if 0 <= selected < len(self._effect_ids):
            self._insert_effect(self._effect_ids[selected])

    def _remove(self):
        if len(self.config["effects"]) <= 1 or not self.chain.curselection():
            return
        try:
            effects = self.collect()['effects']
            index = self.chain.curselection()[0]
            effects.pop(index)
            self._commit_effects(effects, index)
        except ValueError:
            self._refresh_editor_state()

    def _move(self, offset):
        if not self.chain.curselection():
            return
        index = self.chain.curselection()[0]
        dest = index + offset
        if not 0 <= dest < len(self.config["effects"]):
            return
        try:
            effects = self.collect()['effects']
            effects[index], effects[dest] = effects[dest], effects[index]
            self._commit_effects(effects, dest)
        except ValueError:
            self._refresh_editor_state()

    def _preflight_state(self, config):
        selected = self.selected_window()
        return (deepcopy(config), (selected.get('hwnd'), selected.get('pid')) if selected else None,
                self.client.generation, deepcopy(self._host_ready), self._catalog_generation, dict(self.client.settings))

    def _run_preflight(self):
        selected = self.selected_window()
        try:
            config = self.collect()
        except (ValueError, TypeError, tk.TclError) as error:
            return None, [StartIssue('invalid', self._invalid_settings_route(), tr('realtime.preflight.invalid', error=error))]
        try:
            ready = self._host_ready
            if ready is not None and ready.get('_generation') != self.client.generation:
                ready = None
            selection = getattr(self.client, 'runtime_selection', None) if ready else None
            catalog = self.catalog if self._catalog_generation == self.client.generation else {}
            issues = check_start(config, selected, settings=self.client.settings, catalog=catalog,
                                 host=self.client.host, ready=ready,
                                 runtime_selection=selection if isinstance(selection, dict) else None,
                                 target_state=target_window_state(selected) if selected else None)
        except (OSError, ValueError, TypeError) as error:
            issues = [StartIssue('check_failed', 'diagnostics', tr('realtime.preflight.check_failed'), detail=str(error))]
        return config, issues

    def _invalid_settings_route(self):
        try:
            for row in self.parameter_rows.values():
                row.value()
            if self.scale_controls:
                _, _, x, y = self.scale_controls
                if not all(math.isfinite(float(v.get())) and 0 < float(v.get()) <= 16384 for v in (x, y)):
                    return 'effects'
        except (ValueError, TypeError, tk.TclError):
            return 'effects'
        try:
            quality = {k: v.get() if k == 'protection' else float(v.get()) for k, v in self.quality_controls.items()}
            quality['regions'] = [[float(v) for v in line.replace(',', ' ').split()]
                                  for line in self.regions.get('1.0', 'end').splitlines() if line.strip()]
            validate_config({'quality': quality})
        except (ValueError, TypeError, tk.TclError):
            return 'protection'
        return 'display'

    def _present_preflight(self, config, issues):
        self._preflight_issues = issues
        self._preflight_signature = self._preflight_state(config)
        blocking = sum(issue.blocking for issue in issues)
        self.preflight_status.set(tr('realtime.preflight.blocked', count=blocking) if blocking else
                                  tr('realtime.preflight.warnings', count=len(issues)) if issues else tr('realtime.preflight.clear'))
        self.preflight_choice.configure(values=[tr('realtime.preflight.item',
            level=tr('realtime.preflight.blocker' if issue.blocking else 'warning'),
            message=issue.message) for issue in issues])
        if issues:
            self.preflight_choice.current(next((i for i, issue in enumerate(issues) if issue.blocking), 0))
        else:
            self.preflight_choice.set('')
        self.preflight_panel.pack(fill='x', pady=(4, 0))
        self._show_preflight_issue()
        self.continue_button.pack_forget()
        if issues and not blocking:
            self.continue_button.configure(state='normal')
            self.continue_button.pack(side='left', padx=6)
        self._focus_page('startup', self.check_button)
        self.diagnostics.append({'event': 'preflight', 'blocking': blocking,
                                 'issues': [dict(code=i.code, message=i.message, blocking=i.blocking, detail=i.detail) for i in issues]})

    def check_before_start(self):
        if self._pending_start or self._recovering or self._stop_requested:
            self.status.set(tr('realtime.start_pending'))
            return
        config, issues = self._run_preflight()
        self._present_preflight(config, issues)

    def _show_preflight_issue(self, _=None):
        index = self.preflight_choice.current()
        issue = self._preflight_issues[index] if 0 <= index < len(self._preflight_issues) else None
        self.preflight_message.set(issue.message if issue else tr('realtime.preflight.scope'))
        self._preflight_tooltip._hide()
        self._preflight_tooltip.text = (issue.message + '\n' + issue.detail) if issue else tr('realtime.preflight.scope')
        self.locate_button.configure(state='normal' if issue else 'disabled',
            text=tr('diagnostics.export') if issue and issue.route == 'diagnostics' else tr('realtime.preflight.locate'))

    def _focus_page(self, route, widget=None):
        content = self._pages[route]
        target = widget or (self.protection_section if route == 'protection' else content)
        # Locate the actual containing page, including controls that moved to
        # Advanced. Open every collapsed ancestor before calculating offsets.
        cursor = target
        while cursor is not None:
            if isinstance(cursor, CollapsibleSection) and cursor.collapsed:
                cursor.toggle()
            if getattr(cursor, 'master', None) in self._scroll_canvases.values():
                content = cursor
                break
            cursor = getattr(cursor, 'master', None)
        canvas = content.master
        if canvas is not self.stage_canvas:
            self.tabs.select(canvas.master)
        self.window.update_idletasks()
        bounds = canvas.bbox('all')
        if bounds:
            offset = target.winfo_rooty() - content.winfo_rooty()
            canvas.yview_moveto(max(0, offset - 12) / max(1, bounds[3] - bounds[1]))
        focus = widget or canvas
        getattr(focus, 'combo', focus).focus_set()

    def _locate_preflight(self):
        index = self.preflight_choice.current()
        if not 0 <= index < len(self._preflight_issues):
            return
        issue = self._preflight_issues[index]
        if issue.route == 'target':
            self._focus_page('startup', self.target)
        elif issue.route == 'nr_runtime' and self._on_nr_settings:
            self._on_nr_settings()
        elif issue.route in ('runtime', 'nr_runtime'):
            self._focus_page('runtime', self.runtime_button)
        elif issue.route == 'display':
            if issue.code == 'hotkey':
                self._focus_page('display', self.output_selector)
            else:
                self._focus_page('display', self.controls['capture_method'][0])
        elif issue.route == 'protection':
            target = self.regions
            for row in self.quality_rows.values():
                try:
                    row.value()
                except (ValueError, TypeError, tk.TclError):
                    target = row.field
                    break
            self._focus_page('protection', target)
        elif issue.route == 'effects':
            # Do not discard an unfinished numeric draft just to navigate.
            if issue.effect_index is not None:
                self.chain.selection_clear(0, 'end')
                self.chain.selection_set(issue.effect_index)
                self._select_effect()
            target = self.chain
            for row in self.parameter_rows.values():
                try:
                    row.value()
                except (ValueError, TypeError, tk.TclError):
                    target = row.field or row
                    break
            self._focus_page('effects', target)
        elif issue.route == 'diagnostics':
            self.export_diagnostics()
        elif issue.route == 'check':
            self.check_before_start()

    def start(self, *, accept_warnings=False):
        if self._can_start is not None and not self._can_start():
            self.status.set(tr('diagnostics.wait_deep'))
            return
        previous_target = self._session_target
        previous_confirmed = self._render_confirmed
        previous_effects = self._applied_effects
        try:
            if self._pending_start or self._recovering or self._stop_requested:
                self.status.set(tr("realtime.start_pending"))
                return
            selected = self.selected_window()
            config, issues = self._run_preflight()
            self._present_preflight(config, issues)
            if config is None or any(issue.blocking for issue in issues) or (issues and not accept_warnings):
                self.status.set(self.preflight_status.get())
                return
            self.preflight_panel.pack_forget()
            config = effective_nr_skin(config)
            self._queued_parameter_apply = False
            self._queued_quality_apply = False
            self._edit_error = ''
            self._stop_requested = False
            self._render_confirmed = False
            self._applied_effects = []
            self._overlay_expected.clear()
            self._overlay_saved = None
            self._session_target = deepcopy(selected)
            self._pending_start = (deepcopy(selected), config)
            self._start_seen = False
            self._pending_quality = None
            self._live_expected = {}
            self._live_commands.clear()
            self._pending_since = time.monotonic()
            self._rollback_used = False
            self._pending_command = self.client.start(selected["hwnd"], config, selected['pid'])
            self.status.set(tr("realtime.starting"))
        except Exception as error:
            self._pending_start = None
            self.diagnostics.append({'event': 'ui_error', 'operation': 'start', 'message': str(error)})
            self._session_target = previous_target
            self._render_confirmed = previous_confirmed
            self._applied_effects = previous_effects
            messagebox.showerror(tr("realtime.start_failed"), str(error), parent=self.window)
        finally:
            self._notify_session()

    def command(self, name):
        try:
            if name == 'stop':
                self._overlay_expected.clear()
                self._queued_parameter_apply = False
                self._queued_quality_apply = False
                self._stop_requested = True
                self._pending_start = None
                self._pending_quality = None
                self._pending_command = None
                self._recovery_target = None
                self._live_expected = {}
                self._live_commands.clear()
                self.status.set(tr("realtime.stopping"))
                if self._recovering:
                    return  # Recovery already owns teardown; cancel its restart only.
            self.client.send(name, **({'run_id': self._run_id} if name != 'stop' and self._run_id is not None else {}))
        except Exception as error:
            self.status.set(str(error))
            if name == 'stop':
                self._recover(tr("realtime.stop_failed"))
        finally:
            self._notify_session()

    def session_summary(self):
        """Lifecycle only, never editor messages or a newly selected target."""
        busy = bool(self._pending_start or self._recovering or self._native_state or self._active or self._stop_requested)
        if self._closed:
            return tr("realtime.session.closed"), False
        if self._stop_requested:
            phase = tr("realtime.phase.stopping")
        elif self._recovering:
            phase = tr("realtime.phase.recovering") if self._recovery_target else tr("realtime.phase.releasing")
        elif self._native_state == 4:
            phase = tr("realtime.phase.wait_source")
        elif self._pending_start or self._native_state == 1:
            phase = tr("realtime.phase.first_frame") if self._native_state == 2 else tr("realtime.phase.initializing")
        elif self._native_state == 3:
            phase = tr("realtime.phase.stopping")
        elif self._active:
            phase = tr("realtime.phase.running") if self._render_confirmed else tr("realtime.phase.wait_output")
        else:
            phase = tr("realtime.phase.idle")
        target = self._session_target or {}
        title = target.get('title') or target.get('application') or tr("realtime.target_window")
        return tr('realtime.session', phase=phase, target=f' · {title}' if busy else ''), busy

    def _notify_session(self):
        summary, busy = self.session_summary()
        if self.session_text.get() != summary:
            self.session_text.set(summary)
        target_changed = self._target_differs()
        hint = tr('realtime.layout.target_pending' if target_changed else 'realtime.layout.target_running' if busy else 'realtime.layout.target_hint')
        if self.target_hint.get() != hint:
            self.target_hint.set(hint)
        state = 'disabled' if busy else 'normal'
        if getattr(self, '_last_button_state', None) != (busy, state, target_changed):
            self.stop_button.configure(state='normal' if busy else 'disabled')
            self.start_button.configure(text=tr("realtime.start"), state=state)
            self._last_button_state = (busy, state, target_changed)
        output_ready = self._active and self._render_confirmed and not (self._pending_start or self._recovering or self._stop_requested)
        if getattr(self, '_last_output_ready', None) != output_ready:
            for button in self.presentation_buttons.values():
                button.configure(state='normal' if output_ready else 'disabled')
            self._last_output_ready = output_ready
        if self._on_session_change and getattr(self, '_last_session_summary', None) != (summary, busy):
            self._on_session_change(summary, busy)
        self._last_session_summary = (summary, busy)
        self._refresh_editor_state()
        self._refresh_metrics_summary()

    def _target_differs(self):
        selected = self.selected_window()
        running = self._session_target
        return bool(self.session_summary()[1] and selected and running
                    and (selected.get('hwnd'), selected.get('pid')) != (running.get('hwnd'), running.get('pid')))

    def _editor_changed(self):
        if self._editor_building or self._closed:
            return
        snapshot = self._parameter_snapshot()
        if self._edit_snapshot is not None and not self._same_snapshot(snapshot, self._edit_snapshot):
            if self._pending_undo is None:
                self._pending_undo = self._edit_snapshot
        self._edit_snapshot = snapshot
        self._edit_error = ''
        self._refresh_editor_state()

    def _parameter_snapshot(self):
        snapshot = {'parameters': {name: var.get() for name, (_, var, _) in self.parameters.items()}}
        snapshot['toggles'] = {name: var.get() for name, var in self.parameter_toggles.items()}
        if self.extended_range is not None:
            snapshot['extended_range'] = self.extended_range.get()
        if self.scale_controls:
            _, kind, x, y = self.scale_controls
            snapshot['scale'] = (kind.current(), x.get(), y.get())
        return snapshot

    def _same_snapshot(self, left, right):
        if left.get('toggles', {}) != right.get('toggles', {}):
            return False
        if left['parameters'].keys() != right['parameters'].keys():
            return False
        if not all(self._same_parameter(raw, right['parameters'][name]) for name, raw in left['parameters'].items()):
            return False
        a, b = left.get('scale'), right.get('scale')
        return a == b if a is None or b is None else all(self._same_parameter(x, y) for x, y in zip(a, b))

    def _restore_parameter_snapshot(self, snapshot, *, commit=True):
        self._editor_building = True
        try:
            if self.extended_range is not None and 'extended_range' in snapshot:
                self.extended_range.set(snapshot['extended_range'])
                self._update_range_controls()
            for name, raw in snapshot['parameters'].items():
                self.parameters[name][1].set(raw)
            for name, enabled in snapshot.get('toggles', {}).items():
                self.parameter_toggles[name].set(enabled)
            if self.scale_controls and 'scale' in snapshot:
                _, kind, x, y = self.scale_controls
                mode, width, height = snapshot['scale']
                kind.current(mode)
                x.set(width); y.set(height)
                self._update_scale_units()
        finally:
            self._editor_building = False
        self._edit_snapshot = self._parameter_snapshot()
        if commit:
            self._parameter_committed()
        else:
            self._refresh_editor_state()

    def replace_common_parameters(self, index, candidate):
        """A confirmed copy edits the first pass only; never starts/restarts."""
        from dlss5tool.parameter_transfer import COMMON_FIELDS
        self.collect()  # Validate the previously selected editor before moving.
        # A queued earlier gesture must not submit the newly copied draft.
        self._queued_parameter_apply = False
        self.chain.selection_set(index)
        self._select_effect()
        before = self._parameter_snapshot()
        after = deepcopy(before)
        effect = candidate['effects'][index]
        for _, native, _ in COMMON_FIELDS:
            after['parameters'][native] = str(effect['parameters'][native])
            if native in after['toggles']:
                after['toggles'][native] = native not in effect.get('disabled_parameters', [])
        after['parameters']['useAutoMask'] = str(effect['parameters']['useAutoMask'])
        self._undo_parameters, self._pending_undo = before, None
        self._restore_parameter_snapshot(after, commit=False)
        self.status.set(tr('parameter.copied_draft'))

    def _reset_parameters(self, names, *, scale=False):
        before = self._parameter_snapshot()
        after = deepcopy(before)
        for name in names:
            after['parameters'][name] = str(self.parameter_rows[name].descriptor['default'])
            if name in after.get('toggles', {}):
                after['toggles'][name] = True
        if scale and 'scale' in after:
            after['scale'] = (0, '1', '1')
        if self._same_snapshot(after, before):
            return
        self._undo_parameters = before
        self._pending_undo = None
        self._restore_parameter_snapshot(after)

    def _undo_parameter_edit(self):
        snapshot = self._pending_undo if self._pending_undo is not None else self._undo_parameters
        if snapshot is None:
            return
        self._pending_undo = self._undo_parameters = None
        self._restore_parameter_snapshot(snapshot)

    @staticmethod
    def _same_parameter(a, b):
        try:
            return math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-5)
        except (ValueError, TypeError):
            return a == b

    def _parameter_dependency(self, name):
        if not self.parameters:
            return ''
        index = next(iter(self.parameters.values()))[0]
        if self.config['effects'][index]['name'].replace('/', '\\') != NR:
            return ''
        dependency = None
        if name == 'inputResolutionPercent':
            dependency = ('enableInputResolutionScaling', lambda v: v == 1, 'resolution', {})
        elif name in ('amdOpticalFlowMode', 'nvidiaOpticalFlowQuality'):
            amd = name == 'amdOpticalFlowMode'
            dependency = ('opticalFlowMethod', lambda v: v == (1 if amd else 2), 'flow', {'method': 'AMD' if amd else 'NVIDIA'})
        elif name.startswith(('pass2_', 'pass3_')):
            count = int(name[4])
            dependency = ('multiPass', lambda v: v >= count, 'pass', {'count': count})
        if dependency is not None:
            parent, enabled, key, args = dependency
            if parent in self.parameters:
                try:
                    if enabled(self.parameter_rows[parent].value()):
                        return ''
                except (ValueError, tk.TclError):
                    pass
                return tr('realtime.editor.requires_' + key, **args)
        return ''

    def _refresh_parameter_feedback(self):
        applied = self._applied_effects or (self._running_config or {}).get('effects', [])
        running = self._running_config is not None and self.session_summary()[1]
        # Compare what will actually be sent, not the disabled slider's memory.
        effective = effective_nr_skin(self.config)
        pass_count = 1
        if self.pass_toggles:
            try:
                pass_count = self.parameter_rows['multiPass'].value()
            except (ValueError, tk.TclError):
                pass_count = 0
            for count, (enabled, toggle) in self.pass_toggles.items():
                if enabled.get() != (pass_count >= count):
                    enabled.set(pass_count >= count)
                toggle.configure(state='disabled' if pass_count == 0 or (count == 3 and pass_count < 2) else 'normal')
        for name, row in self.parameter_rows.items():
            index, var, _ = self.parameters[name]
            default = row.descriptor['default']
            same_effect = index < len(applied) and applied[index]['name'] == self.config['effects'][index]['name']
            actual = applied[index].get('parameters', {}).get(name, default) if same_effect else default
            expected = effective['effects'][index].get('parameters', {}).get(name, var.get())
            try:
                value, error = row.value(), ''
            except (ValueError, tk.TclError) as exc:
                value, error = var.get(), str(exc)
            row.set_feedback(reason=self._parameter_dependency(name),
                             nondefault=(not self._same_parameter(value, default)
                                         or (name in self.parameter_toggles and not self.parameter_toggles[name].get())),
                             unapplied=running and (not same_effect or not self._same_parameter(expected, actual)),
                              pending=((index, name) in self._overlay_expected or (index, name) in self._live_expected),
                             error=error)
        for strength, mask in self.skin_pairs.items():
            row, switch = self.parameter_rows[strength], self.parameter_rows[mask]
            row.set_feedback(reason=row.disabled_reason,
                             nondefault=row.nondefault or switch.nondefault,
                             unapplied=row.unapplied or switch.unapplied,
                              pending=row._feedback_state[4] or switch._feedback_state[4],
                             error=row._feedback_state[3] or switch._feedback_state[3])
        for key, (title, names) in self._parameter_groups.items():
            count = sum(self.parameter_rows[name].nondefault for name in names
                        if name not in self.skin_pairs.values() and (name != 'multiPass' or not self.pass_toggles))
            if key == 'resolution' and self.scale_controls:
                _, mode, x, y = self.scale_controls
                count += int(mode.current() != 0 or not all(self._same_parameter(v.get(), 1) for v in (x, y)))
            if key in ('pass2', 'pass3') and self.pass_toggles:
                title += ' · ' + tr('realtime.editor.pass_on' if pass_count >= int(key[-1]) else 'realtime.editor.pass_off')
            self.parameter_sections[key].set_title(title + (f' · {count}' if count else ''))
        undo_state = 'normal' if self._pending_undo is not None or self._undo_parameters is not None else 'disabled'
        if self.undo_button.cget('state') != undo_state:
            self.undo_button.configure(state=undo_state)

    def _effect_changes(self, config):
        """Compare all effects, including drafts in folded/unselected editors."""
        config = effective_nr_skin(config)
        applied = self._applied_effects or (self._running_config or {}).get('effects', [])
        if len(applied) != len(config['effects']):
            return True, []
        changes = []
        restart = False
        for index, (draft, actual) in enumerate(zip(config['effects'], applied)):
            if (draft['name'] != actual['name'] or
                    any(draft.get(k, default) != actual.get(k, default)
                        for k, default in (('scale', [1, 1]), ('scaling_type', 0)))):
                return True, []
            descriptors = {p['name']: p for p in self.catalog.get(draft['name'], {}).get('parameters', [])}
            names = set(draft.get('parameters', {})) | set(actual.get('parameters', {}))
            for name in names:
                default = descriptors.get(name, {}).get('default')
                value = draft.get('parameters', {}).get(name, default)
                previous = actual.get('parameters', {}).get(name, default)
                if self._same_parameter(value, previous):
                    continue
                if name not in descriptors or self._parameter_modes.get((index, name)) != 1:
                    restart = True
                else:
                    changes.append((index, name, value))
        return restart, changes

    def _refresh_editor_state(self):
        if self._editor_building or self._closed:
            return
        state = 'idle'
        validation_error = ''
        changes = []
        quality_changed = False
        config = None
        try:
            config = self.collect()
            if self._pending_start or self._recovering or self._stop_requested:
                state = 'waiting'
            elif self._active and self._render_confirmed and self._running_config is not None:
                restart, changes = self._effect_changes(config)
                restart |= self._target_differs()
                restart |= any(config[k] != self._running_config.get(k) for k in config if k not in ('effects', 'quality'))
                quality_changed = config['quality'] != self._running_config.get('quality')
                state = ('applying' if self._live_expected or self._pending_quality or self._overlay_expected else
                         'restart' if restart else 'dirty' if changes or quality_changed else 'clean')
            elif self.session_summary()[1]:
                state = 'waiting'
        except (ValueError, TypeError, tk.TclError) as error:
            state = 'invalid'
            validation_error = str(error)
        if state == 'clean':
            self._edit_error = ''
        if self._edit_error and state == 'dirty':
            state = 'failed'
        self._editor_state = state
        if state == 'invalid':
            text = tr('realtime.editor.invalid', error=validation_error)
        elif state == 'failed':
            text = tr('realtime.editor.apply_failed', error=self._edit_error)
        elif state == 'restart':
            text = tr('realtime.editor.restart_reason', reason=self._restart_reason(config))
        elif state == 'dirty':
            text = tr('realtime.editor.dirty_count', count=len(changes) + int(quality_changed))
        elif state == 'applying':
            text = tr('realtime.editor.applying_count', count=len(self._live_expected) + len(self._overlay_expected) + int(self._pending_quality is not None))
        else:
            text = tr('realtime.editor.' + state)
        if self.editor_status.get() != text:
            self.editor_status.set(text)
            if state in ('invalid', 'failed'):
                self.diagnostics.append({'event': 'ui_error', 'operation': 'apply', 'message': text, 'run_id': self._run_id})
        button = (tr('realtime.layout.switch_target') if state == 'restart' and self._target_differs() else
                  tr('realtime.editor.restart_action') if state == 'restart' else
                  tr('realtime.editor.retry') if state == 'failed' else tr('realtime.editor.apply'))
        appearance = (button, 'normal' if state in ('dirty', 'restart', 'failed') else 'disabled')
        if getattr(self, '_editor_button_state', None) != appearance:
            self.apply_button.configure(text=appearance[0], state=appearance[1])
            self._editor_button_state = appearance
        show_action = state in ('dirty', 'restart', 'failed')
        if show_action and not self.apply_button.winfo_manager():
            self.apply_button.pack(fill='x', pady=(4, 0))
        elif not show_action and self.apply_button.winfo_manager():
            self.apply_button.pack_forget()
        self._refresh_parameter_feedback()
        self._refresh_chain_summary(state)
        if self._preflight_signature is not None and self._preflight_signature != self._preflight_state(config):
            self.preflight_status.set(tr('realtime.preflight.stale'))
            self.continue_button.configure(state='disabled')

    def _refresh_chain_summary(self, state):
        draft = deepcopy(self.config['effects'])
        for name, (index, var, _) in self.parameters.items():
            if index < len(draft):
                draft[index].setdefault('parameters', {})[name] = var.get()
        self.chain.update_subtitles([step_subtitle(effect, self.catalog) for effect in draft])
        key = 'current' if state == 'clean' else 'invalid' if state == 'invalid' else 'pending' if self.session_summary()[1] else 'draft'
        self.draft_summary.set(tr('realtime.summary.' + key, chain=chain_summary(draft, self.catalog)))
        draft_full = chain_summary(draft, self.catalog, max_items=None)
        if self._pending_start or self._recovering or self._stop_requested or self._native_state in (1, 3):
            text = tr('realtime.summary.waiting')
            full = text
        elif self._render_confirmed and self._running_config and self.session_summary()[1]:
            effects = self._applied_effects or self._running_config['effects']
            key = 'paused' if self._native_state == 4 else 'running'
            text = tr('realtime.summary.' + key, chain=chain_summary(effects, self.catalog))
            full = chain_summary(effects, self.catalog, max_items=None)
        else:
            text = tr('realtime.summary.not_running')
            full = text
        self.running_summary.set(text)
        self.chain_summary_help.set_details(tr('realtime.summary.pending', chain=draft_full) + '\n' + text)
        show_difference = state in ('dirty', 'restart', 'failed', 'invalid') and self.session_summary()[1]
        if show_difference and not self.chain_summary_help.winfo_manager():
            self.chain_summary_help.pack(fill='x', pady=3, before=self.add_section)
        elif not show_difference and self.chain_summary_help.winfo_manager():
            self.chain_summary_help.pack_forget()

    def _restart_reason(self, config):
        config = effective_nr_skin(config)
        applied = self._applied_effects or self._running_config.get('effects', [])
        reasons = []
        if self._target_differs():
            reasons.append(tr('realtime.layout.source'))
        if [e['name'] for e in config['effects']] != [e['name'] for e in applied]:
            reasons.append(tr('realtime.editor.reason_chain'))
        else:
            if any(d.get('scaling_type', 0) != a.get('scaling_type', 0) or d.get('scale', [1, 1]) != a.get('scale', [1, 1])
                   for d, a in zip(config['effects'], applied)):
                reasons.append(tr('realtime.editor.reason_scale'))
            count = 0
            for index, (draft, actual) in enumerate(zip(config['effects'], applied)):
                defaults = {p['name']: p['default'] for p in self.catalog.get(draft['name'], {}).get('parameters', [])}
                for name in set(draft.get('parameters', {})) | set(actual.get('parameters', {})):
                    if (self._parameter_modes.get((index, name)) != 1
                            and not self._same_parameter(draft.get('parameters', {}).get(name, defaults.get(name)),
                                                        actual.get('parameters', {}).get(name, defaults.get(name)))):
                        count += 1
            if count:
                reasons.append(tr('realtime.editor.reason_parameters', count=count))
        if any(config[k] != self._running_config.get(k) for k in config if k not in ('effects', 'quality')):
            reasons.append(tr('realtime.editor.reason_display'))
        return ' · '.join(reasons) or tr('realtime.editor.reason_chain')

    def _apply_editor(self):
        self._refresh_editor_state()
        if self._editor_state == 'failed':
            self._edit_error = ''
            self._refresh_editor_state()
        if self._editor_state == 'restart':
            self.start()
        elif self._editor_state == 'dirty':
            self.live_parameters()
            if self.collect()['quality'] != self._running_config.get('quality'):
                self.apply_quality()
        self._refresh_editor_state()

    def _parameter_committed(self):
        self._editor_changed()
        if self._pending_undo is not None:
            self._undo_parameters = self._pending_undo
            self._pending_undo = None
        self._refresh_parameter_feedback()
        if self._active and self._render_confirmed and not (self._pending_start or self._stop_requested or self._recovering):
            if self._live_expected or self._overlay_expected:
                self._queued_parameter_apply = True
            elif self._editor_state not in ('invalid', 'restart'):
                self.live_parameters()

    def _quality_committed(self):
        self._editor_changed()
        if (self._active and self._render_confirmed
                and self._editor_state not in ('invalid', 'restart', 'waiting')):
            if self._pending_quality:
                self._queued_quality_apply = True
            else:
                self.apply_quality()
        self._refresh_editor_state()

    def live_parameters(self):
        if self._target_differs():
            # In-flight quality/overlay acknowledgements can keep the editor
            # in 'applying'. Still never send the pending source's parameters
            # into the old session, or discard that session's pending receipt.
            self._refresh_editor_state()
            return
        try:
            if not self._active or self._pending_start:
                raise ValueError(tr("realtime.wait_output"))
            restart, changes = self._effect_changes(self.collect())
            if restart:
                raise ValueError(tr('realtime.editor.restart'))
            if self._live_expected or self._overlay_expected:
                self._queued_parameter_apply = True
                return
            self._live_expected = {(i, n): v for i, n, v in changes}
            self._live_commands.clear()
            self._live_sent_at = time.monotonic()
            for index, name, value in changes:
                self._live_commands.add(self.client.send('set_parameter', effect=index, name=name, value=value, run_id=self._run_id))
            if not changes and self._running_config is not None:
                # A remembered switch at zero can change without changing any
                # effective native value. Persist it without a redundant send.
                remembered = restore_nr_skin_memory(self._running_config, self.config)
                if remembered != self._running_config:
                    self._save_running_session()
            self.status.set(tr("realtime.parameters_pending") if changes else tr("realtime.parameters_unchanged"))
        except Exception as error:
            self._live_expected = {}
            self._live_commands.clear()
            self._queued_parameter_apply = False
            self._edit_error = str(error)
            self.status.set(str(error))
        self._refresh_editor_state()

    def save_preset(self):
        name = simpledialog.askstring(tr("realtime.save_preset"), tr("realtime.preset_name"), parent=self.window)
        if not name:
            return
        try:
            selected = self.selected_window()
            app = selected["application"] if selected and self.bind_app.get() else ""
            self.store.save(name, self.collect(), app)
            self.preset_choice.configure(values=sorted(self.store.data["presets"]))
            self.preset_choice.set(name.strip())
            self.status.set(tr("realtime.preset_saved") + (tr("realtime.preset_bound") if app else ""))
        except Exception as error:
            messagebox.showerror(tr("realtime.save_failed"), str(error), parent=self.window)

    def load_preset(self):
        config = self.store.data["presets"].get(self.preset_choice.get())
        if config:
            self.apply_config(config)

    def save_nr(self):
        name = simpledialog.askstring(tr("realtime.save_nr_title"), tr("realtime.preset_name"), parent=self.window)
        if name:
            try:
                self.store.save_nr(name, self.collect())
                self.nr_choice.configure(values=sorted(self.store.data['nr_presets']))
                self.nr_choice.set(name.strip())
            except Exception as error:
                self.status.set(str(error))

    def load_nr(self):
        preset = self.store.data.get('nr_presets', {}).get(self.nr_choice.get())
        if preset:
            try:
                self.apply_config(apply_nr_preset(self.collect(), preset))
                self.status.set(tr("realtime.nr_loaded"))
            except Exception as error:
                self.status.set(str(error))

    def export_config(self):
        from pathlib import Path
        filename = filedialog.asksaveasfilename(parent=self.window, defaultextension=".json", filetypes=[("JSON", "*.json")])
        if filename:
            try:
                data = nr_preset(self.collect()) if self.nr_export.get() else {'version': 1, 'config': portable_config(self.collect())}
                Path(filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as error:
                messagebox.showerror(tr("realtime.export_failed"), str(error), parent=self.window)

    def import_config(self):
        from pathlib import Path
        filename = filedialog.askopenfilename(parent=self.window, filetypes=[("JSON", "*.json")])
        if filename:
            try:
                path = Path(filename)
                if path.stat().st_size > 1024**2:
                    raise ValueError(tr("realtime.config_too_large"))
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("version") != 1:
                    raise ValueError(tr("realtime.config_version"))
                if data.get('kind') == 'nr-only':
                    self.apply_config(apply_nr_preset(self.collect(), data))
                else:
                    imported = portable_config(data['config'])
                    current = self.collect()
                    imported.update({k: current[k] for k in ('gpu_index', 'monitor_id', 'monitor_mode')})
                    self.apply_config(imported)
            except Exception as error:
                messagebox.showerror(tr("realtime.import_failed"), str(error), parent=self.window)

    def _recover(self, reason):
        self._overlay_expected.clear()
        self._overlay_saved = None
        if self._recovering:
            return
        self.diagnostics.append({'event': 'recovery', 'message': reason, 'run_id': self._run_id})
        self._queued_parameter_apply = False
        self._queued_quality_apply = False
        candidate = deepcopy(self._known_good) if self._known_good and not self._rollback_used and not self._stop_requested else None
        self._rollback_used = True
        self._pending_start = None
        self._pending_command = None
        self._active = False
        self._native_state = 0
        self._render_confirmed = False
        self._recovering = True
        self._gpu_sampling = False
        self._pending_quality = None
        self._live_expected = {}
        self._live_commands.clear()
        self._recovery_target = candidate
        self.status.set(reason + (tr("realtime.recovery_restart") if candidate else tr("realtime.recovery_release")))
        def shutdown():
            try:
                self.client.close()
                self._recovery.put(None)
            except Exception as error:
                self._recovery.put(str(error))
        threading.Thread(target=shutdown, name='realtime-recovery', daemon=False).start()

    def _confirm_session(self):
        if self._pending_start and self._start_seen and not self._stop_requested:
            self._render_confirmed = True
            self._known_good = deepcopy(self._pending_start)
            self._known_settings = dict(self.client.settings)
            self._running_config = deepcopy(self._pending_start[1])
            self._pending_start = None
            self._pending_command = None
            try:
                self._save_running_session()
            except Exception as error:
                self.status.set(tr('realtime.save_after_output_failed', error=error))
                return
            self.status.set(tr("realtime.output_ready") + (tr("realtime.output_restored") if self._rollback_used else ''))

    def _save_running_session(self):
        remembered = restore_nr_skin_memory(self._running_config, self.config)
        persisted = deepcopy(remembered)
        if self._overlay_saved:
            # Confirming an unrelated live/quality edit must not erase an
            # already saved native edit that still requires restart.
            for key in ('sync_enabled', 'frame_rate', 'sync_mode'):
                persisted[key] = self._overlay_saved[key]
            for index, (saved, actual) in enumerate(zip(self._overlay_saved['effects'], persisted['effects'])):
                if saved['name'] != actual['name']:
                    continue
                for name, value in saved.get('parameters', {}).items():
                    if self._parameter_modes.get((index, name)) != 1 or (index, name) in self._overlay_expected:
                        actual.setdefault('parameters', {})[name] = value
            persisted = restore_nr_skin_memory(persisted, self.config)
        self.store.save_session(persisted)
        if self._overlay_saved:
            self._overlay_saved = deepcopy(persisted)
        if self._known_good:
            self._known_good = (self._known_good[0], deepcopy(remembered))

    def _poll(self):
        if self._closed:
            return
        if self._recovering:
            try:
                error = self._recovery.get_nowait()
            except queue.Empty:
                self._notify_session()
                self._after = self.window.after(100, self._poll)
                return
            self._recovering = False
            self._stop_requested = False
            while not self.client.events.empty():
                try:
                    pending_event = self.client.events.get_nowait()
                    if (pending_event.get('_generation', self.client.generation) == self.client.generation
                            and pending_event.get('event') in ('emergency_stop', 'safety_stop')):
                        self._recovery_target = None
                except queue.Empty: break
            if self._recovery_target and not error:
                selected, config = self._recovery_target
                self._recovery_target = None
                self.client.settings = dict(self._known_settings)
                self._pending_start = (selected, config)
                self._session_target = deepcopy(selected)
                self._start_seen = False
                self._pending_since = time.monotonic()
                try:
                    self._pending_start = (selected, effective_nr_skin(config))
                    self._pending_command = self.client.start(selected['hwnd'], self._pending_start[1], selected['pid'])
                    self.apply_config(config)
                except Exception as failure:
                    self._pending_start = None
                    self.status.set(tr('realtime.restore_failed', error=failure))
            elif error:
                self._stop_requested = True  # Teardown unconfirmed; keep emergency control reachable.
                self.status.set(tr('realtime.release_failed', error=error))
            else:
                self.status.set(tr("realtime.stopped_source"))
        for batch in self._event_batches():
            event = batch[-1]
            kind = event.get("event")
            if event.get('_generation', self.client.generation) != self.client.generation:
                continue
            for item in batch:
                self.diagnostics.append({'time': time.time(), **item})
            if kind == 'ready':
                self._host_ready = dict(event, _generation=self.client.generation)
                registered = event.get('stop_hotkey_registered', event.get('hotkeys', {}).get('stop'))
                key = ('realtime.safety.protected' if event.get('independent_stop') else 'workbench.emergency_stop') if registered else 'realtime.safety.unavailable'
                self.stop_hint.set(tr(key))
                control_key = 'realtime.control.unavailable' if event.get('hotkeys', {}).get('parameters') is False else 'realtime.control.help'
                self._control_tip.text = tr(control_key)
                if control_key == 'realtime.control.unavailable':
                    self._write_log(tr(control_key))
            elif kind in ('fatal', 'exited'):
                self._host_ready = None
                self.stop_hint.set(tr('realtime.safety.checking'))
            if kind in ('emergency_stop', 'safety_stop'):
                self.command('stop')  # Clear pending applies/restarts as well as the native session.
                if kind == 'safety_stop':
                    self._recover(tr('realtime.safety.forced'))
                    break
                continue
            if kind == 'safety_error':
                self.status.set(tr('realtime.safety.failed', error=event.get('message', '')))
                continue
            if kind == 'cursor_restore' and not event.get('ok'):
                self.status.set(tr('realtime.safety.cursor_failed'))
                continue
            if kind == 'exited' and event.get('returncode') not in (None, 0) and self.session_summary()[1]:
                # A crash is not a recoverable preset rejection. Never re-enter
                # fullscreen behind the user's emergency escape attempt.
                self._stop_requested = True
            summary = event_summary(event)
            if summary:
                self._write_log(summary)
            if kind == 'capture_fallback':
                if self._pending_start:
                    self._pending_start = (self._pending_start[0], validate_config(event['config']))
                self.controls['capture_method'][0].current(event['config']['capture_method'])
                self.status.set(tr('realtime.log.capture_fallback'))
            if kind == 'gpu_load':
                self._gpu_sampling = False
                boards = event.get('boards', [])
                def label(value, unit): return tr("realtime.unavailable") if value is None else f'{value:.1f}{unit}'
                self.gpu_load.set(tr("realtime.gpu_prefix") + ' · '.join(f"{b['name']}：{label(b['utilization'], '%')} / {label(b['memory_mib'], ' MiB')} / {label(b['watts'], ' W')}" for b in boards) if boards else tr("realtime.gpu_unavailable"))
                continue
            if kind == 'devices':
                self._monitors = event['monitors']; self._adapters = event['adapters']
                self.monitor_picker.configure(values=[f"{m['name']} · {m['rect']} · {tr("realtime.hdr_active") if m.get('hdr_active') else 'SDR'}" for m in self._monitors])
                self.gpu_picker.configure(values=[tr("realtime.automatic")]+[f"{a['index']}: {a['name']}" for a in self._adapters])
                self.gpu_picker.current(0)
            elif kind == 'status':
                if event.get('run_id') != self._run_id:
                    continue
                if self._stop_requested and event.get('state') == 0:
                    self._native_state = 0
                    self._active = self._stop_requested = self._render_confirmed = False
                    self.status.set(tr("realtime.stopped"))
                now = time.monotonic()
                current = event.get('metrics', {})
                self._parameter_modes = {(p['effect'], p['name']): p['mode'] for p in event.get('parameter_modes', [])}
                self._applied_effects = event.get('effects', [])
                self._confirm_overlay_parameters(event)
                if current.get('nr_failures', 0):
                    self._recover(tr("realtime.nr_failed"))
                    break
                if current.get('submitted', 0) > 0 and event.get('state') == 2:
                    self._confirm_session()
                    if not self._pending_start and not self._stop_requested:
                        self._render_confirmed = True
                if self._live_expected and all(i < len(self._applied_effects) and abs(self._applied_effects[i].get('parameters', {}).get(n, float('inf')) - v) < 1e-5 for (i,n),v in self._live_expected.items()):
                    self._live_expected = {}
                    self._live_commands.clear()
                    if self._running_config:
                        self._running_config['effects'] = deepcopy(self._applied_effects)
                        if self._known_good: self._known_good = (self._known_good[0], deepcopy(self._running_config))
                        try: self._save_running_session()
                        except Exception as error: self.status.set(str(error))
                        else: self.status.set(tr("realtime.parameters_saved"))
                if (self._pending_quality and self._pending_quality['revision'] is not None
                        and self._pending_quality['run_id'] == event.get('run_id')
                        and event.get('quality_revision') == event.get('quality_applied_revision') == self._pending_quality['revision']):
                    if self._running_config:
                        self._running_config['quality'] = self._pending_quality['quality']
                        if self._known_good: self._known_good = (self._known_good[0], deepcopy(self._running_config))
                        try: self._save_running_session()
                        except Exception as error: self.status.set(str(error))
                        else: self.status.set(tr("realtime.quality_saved"))
                    self._pending_quality = None
                sample_due = (self._last_metrics is None or self._last_metrics[0] != event.get('run_id')
                              or now - self._last_metrics[1] >= 1)
                if sample_due and self._last_metrics and self._last_metrics[0] == event.get('run_id'):
                    _, previous_time, previous = self._last_metrics
                    seconds = max(.001, now-previous_time)
                    rates = {k: max(0, (current.get(k,0)-previous.get(k,0))/seconds) for k in ('captured', 'nr_evaluations', 'real', 'submitted')}
                    age = current.get('dequeue_to_submit_ms_p95')
                    age_text = f'{age:.1f} ms' if age is not None else tr("realtime.unavailable")
                    generated = current.get('generated')
                    gen_text = tr("realtime.unavailable") if generated is None or previous.get('generated') is None else f"{max(0,(generated-previous['generated'])/seconds):.1f}"
                    gpu = current.get('nr_gpu_ms_p95')
                    gpu_text = f'{gpu:.1f} ms' if gpu is not None else tr("realtime.unavailable")
                    self.metrics.set(tr('realtime.metrics', capture=rates['captured'], nr=rates['nr_evaluations'],
                                        real=rates['real'], generated=gen_text, submitted=rates['submitted'],
                                        age=age_text, gpu=gpu_text, discarded=current.get('discarded_capture', 0)))
                    self._metrics_compact = tr('realtime.metrics_compact', real=rates['real'], gpu=gpu_text)
                    self._metrics_run_id = event.get('run_id')
                if sample_due:
                    self._last_metrics = (event.get('run_id'), now, current)
                continue
            if kind == "catalog":
                self.catalog = {effect["name"]: effect for effect in event["effects"]}
                self._catalog_generation = self.client.generation
                self._filter_effects()
                selected = self.chain.curselection()
                self._render_chain(selected[0] if selected else 0)
                self.status.set(tr('realtime.catalog_loaded', count=len(self.catalog)))
                continue
            if kind == "state":
                value = event.get("state")
                if (value in (1, 2) and event.get('run_id') != self._run_id and self._overlay_saved
                        and not self._pending_start and not self._stop_requested):
                    # Native-panel restart: saved settings become running only
                    # after output from this new session has been confirmed.
                    self._pending_start = (deepcopy(self._session_target), effective_nr_skin(self._overlay_saved))
                    self._start_seen = True
                    self._pending_since = time.monotonic()
                    self._render_confirmed = False
                    self._overlay_expected.clear()
                    self._applied_effects = []
                self._native_state = value
                self._run_id = event.get('run_id')
                self._active = value == 2
                if value == 1 and self._pending_start:
                    self._start_seen = True
                if value == 0:
                    self._overlay_expected.clear()
                    self._queued_parameter_apply = False
                    self._queued_quality_apply = False
                    self._stop_requested = False
                    self._render_confirmed = False
                    self._pending_quality = None
                    self._live_expected = {}
                    self._live_commands.clear()
                if value == 0 and self._pending_start:
                    self._recover(tr("realtime.init_failed"))
                    break
                self.status.set({0: tr("realtime.stopped"), 1: tr("realtime.initializing"), 2: tr("realtime.init_wait_output") if self._pending_start else tr("realtime.running"), 3: tr("realtime.stopping_short"), 4: tr("realtime.phase.wait_source")}.get(value, str(value)))
            elif kind == 'settings_requested':
                self._receive_overlay_settings(batch)
            elif (kind == 'ack' and self._pending_quality and event.get('id') == self._pending_quality['command']
                  and event.get('run_id', self._pending_quality['run_id']) == self._pending_quality['run_id']):
                if event.get('ok') and event.get('run_id') == self._pending_quality['run_id']:
                    self._pending_quality['revision'] = event.get('quality_revision')
                else:
                    self._pending_quality = None
                    self._queued_quality_apply = False
                    self._edit_error = native_message(event)
                    self.status.set(self._edit_error)
            elif (kind == 'ack' and not event.get('ok')
                  and event.get('id') not in self._live_commands | {self._pending_command}):
                # An unrelated action may fail while parameter edits are in
                # flight. Report it without cancelling their confirmation.
                if event.get('run_id', self._run_id) == self._run_id:
                    self.status.set(native_message(event))
            elif kind in ("error", "fatal", "exited") or (kind == "ack" and not event.get("ok")):
                if (kind == 'ack' and event.get('id') != self._pending_command
                        and event.get('run_id', self._run_id) != self._run_id):
                    continue
                if (kind in ('error', 'fatal', 'exited') and self.session_summary()[1]) or (kind == 'ack' and event.get('id') == self._pending_command):
                    self._recover(native_message(event))
                    break
                if self._live_expected:
                    self._edit_error = native_message(event)
                self._live_expected = {}
                self._live_commands.clear()
                self._queued_parameter_apply = False
                self.status.set(native_message(event))
            elif kind == 'ready':
                failed = [k for k,v in event.get('hotkeys', {}).items() if not v]
                if failed:
                    self.status.set(summary)
        if self._live_expected and time.monotonic() - self._live_sent_at > 5:
            self._live_expected = {}
            self._live_commands.clear()
            self._queued_parameter_apply = False
            self._edit_error = tr('realtime.editor.timeout')
        if self._overlay_expected and time.monotonic() - self._overlay_sent_at > 5:
            self._overlay_expected.clear()
            self._edit_error = tr('realtime.editor.timeout')
        if self._pending_quality and time.monotonic() - self._pending_quality['sent_at'] > 5:
            self._pending_quality = None
            self._queued_quality_apply = False
            self._edit_error = tr('realtime.editor.quality_timeout')
        if self._queued_parameter_apply and not self._live_expected and not self._overlay_expected:
            self._queued_parameter_apply = False
            self._parameter_committed()
        if self._queued_quality_apply and not self._pending_quality:
            self._queued_quality_apply = False
            self._quality_committed()
        if self._pending_start and time.monotonic() - self._pending_since > 30:
            self._recover(tr("realtime.output_timeout"))
        if self.session_summary()[1] and not self._recovering and time.monotonic() - self._last_status_request >= 1:
            self._last_status_request = time.monotonic()
            try:
                self.client.send('status')
            except Exception as error:
                self.status.set(str(error)); self._active = False
        if self._active and not self._gpu_sampling and time.monotonic() - self._last_gpu_sample >= 2:
            self._gpu_sampling = True
            self._last_gpu_sample = time.monotonic()
            generation = self.client.generation
            def sample():
                self.client._put(dict(event='gpu_load', **sample_gpu_load()), generation)
            threading.Thread(target=sample, name='realtime-gpu-monitor', daemon=True).start()
        self._notify_session()
        self._after = self.window.after(100, self._poll)

    def close(self):
        if self._closed:
            return
        self._splitter_cancel()
        self._closed = True
        if self._on_session_change:
            self._on_session_change(*self.session_summary())
        if self._after:
            self.window.after_cancel(self._after)
        if getattr(self, '_diagnostic_after', None):
            self.window.after_cancel(self._diagnostic_after)
        self.status.trace_remove('write', self._status_trace)
        # Non-daemon: let native teardown release cursor/input even when this
        # is also the main application's final window.
        if not self._recovering:
            threading.Thread(target=self.client.close, daemon=False, name='realtime-shutdown').start()
        self.log.frame.destroy()
        self.window.destroy()


class RealtimeWindow(RealtimeWorkspace):
    """Standalone diagnostic harness only; the application embeds the workspace."""
    def __init__(self, parent, settings=None):
        self._shell = tk.Toplevel(parent)
        self._shell.title(tr("realtime.window_title"))
        self._shell.geometry('1040x760')
        self._shell.minsize(800, 600)
        ui_theme.apply_ttk(self._shell, ui_theme.tokens('dark'))
        try:
            super().__init__(self._shell, settings)
        except Exception:
            self._shell.destroy()
            raise
        self.window.pack(fill='both', expand=True)
        self._shell.bind('<MouseWheel>', self.on_mousewheel)
        self._shell.protocol('WM_DELETE_WINDOW', self.close)

    def close(self):
        super().close()
        if self._shell.winfo_exists():
            self._shell.destroy()
