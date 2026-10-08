"""Status-bar mode feedback lifetime, independent of media or native capture."""
import tkinter as tk
import unittest
from unittest import mock

from dlss5tool import ui_theme
from dlss5tool.workbench_transition import WorkbenchTransition


class WorkbenchTransitionTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        ui_theme.configure_fonts(self.root)
        self.host = tk.Frame(self.root)
        self.host.pack(fill='both', expand=True)
        self.transition = WorkbenchTransition(
            self.host, ui_theme.tokens('dark'), 'Local media',
            ('Local media', 'Realtime enhancement'))
        self.addCleanup(self.transition.cancel)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        mapped = mock.patch.object(self.host, 'winfo_ismapped', return_value=True)
        mapped.start()
        self.addCleanup(mapped.stop)
        motion = mock.patch('dlss5tool.workbench_transition.animations_enabled', return_value=False)
        motion.start()
        self.addCleanup(motion.stop)

    def test_highlight_expires_but_current_mode_stays_visible(self):
        transition = self.transition
        with mock.patch.object(transition, 'NOTICE_MS', 1):
            transition.begin(ui_theme.tokens('light'), 'Realtime enhancement')
            self.assertEqual(transition.title, 'Local media')
            transition.reveal()
            timer = transition._after
            transition.reveal()
            self.assertEqual(transition._after, timer)
            self.root.after(50, self.root.quit)
            self.root.mainloop()
        self.assertIsNone(transition._after)
        self.assertEqual(transition.title, 'Realtime enhancement')
        self.assertEqual(transition.badge.winfo_manager(), 'pack')
        self.assertEqual(transition.badge.itemcget(transition._text, 'fill'),
                         ui_theme.tokens('light')['muted'])
        self.assertEqual(self.errors, [])

    def test_rapid_switch_reuses_badge_and_cancels_old_timer(self):
        transition = self.transition
        badge = transition.badge
        transition.begin(ui_theme.tokens('dark'), 'Realtime enhancement')
        transition.reveal()
        old_timer, old_generation = transition._after, transition._generation
        transition.begin(ui_theme.tokens('light'), 'Local media')
        transition.reveal()
        timer = transition._after
        transition._notice_step(old_generation)
        self.assertIs(transition.badge, badge)
        self.assertEqual(transition._after, timer)
        self.assertNotIn(old_timer, self.root.tk.call('after', 'info'))
        self.assertEqual(transition.title, 'Local media')
        self.assertEqual(badge.cget('bg'), ui_theme.tokens('light')['surface'])

    def test_badge_has_fixed_geometry_and_no_overlay_in_both_themes(self):
        transition = self.transition
        geometry = transition.badge.pack_info()
        for theme, title in (('light', 'Realtime enhancement'), ('dark', 'Local media')):
            transition.begin(ui_theme.tokens(theme), title)
            transition.reveal()
            self.assertEqual(transition.badge.pack_info(), geometry)
            self.assertEqual(self.host.winfo_children(), [transition.badge])
            self.assertEqual(str(transition.badge.cget('takefocus')), '0')
            self.assertEqual(int(transition.badge.cget('highlightthickness')), 0)
            self.assertIsNone(transition.cover)
            self.assertIsNone(transition.notice)

    def test_failed_switch_keeps_previous_mode_label(self):
        self.transition.begin(ui_theme.tokens('light'), 'Realtime enhancement')
        self.transition.cancel()
        self.transition.reveal()
        self.assertEqual(self.transition.title, 'Local media')
        self.assertIsNone(self.transition._after)

    def test_startup_label_can_be_restored_without_a_highlight(self):
        self.transition.begin(ui_theme.tokens('light'), 'Realtime enhancement')
        self.transition.reveal(highlight=False)
        self.assertEqual(self.transition.title, 'Realtime enhancement')
        self.assertIsNone(self.transition._after)
        self.assertEqual(self.transition._strength, 0)
        self.assertEqual(self.transition.badge.itemcget(self.transition._text, 'fill'),
                         ui_theme.tokens('light')['muted'])

    def test_normal_motion_fades_to_resting_text_without_displacement(self):
        transition = self.transition
        with mock.patch('dlss5tool.workbench_transition.animations_enabled', return_value=True):
            transition.begin(ui_theme.tokens('dark'), 'Realtime enhancement')
            transition.reveal()
        geometry = transition.badge.pack_info()
        colors = []
        for elapsed in (.05, .35, .6, .75):
            self.host.after_cancel(transition._after)
            with mock.patch('dlss5tool.workbench_transition.time.monotonic',
                            return_value=transition._started + elapsed):
                transition._notice_step()
            colors.append(transition.badge.itemcget(transition._text, 'fill'))
            self.assertEqual(transition.badge.pack_info(), geometry)
        self.assertEqual(colors[0], ui_theme.tokens('dark')['accent'])
        self.assertEqual(colors[-1], ui_theme.tokens('dark')['muted'])
        self.assertNotEqual(colors[1], colors[0])
        self.assertIsNone(transition._after)
        self.assertEqual(transition.title, 'Realtime enhancement')

    def test_hidden_workbench_commits_label_without_animation(self):
        with mock.patch.object(self.host, 'winfo_ismapped', return_value=False):
            self.transition.begin(ui_theme.tokens('light'), 'Realtime enhancement')
            self.transition.reveal()
        self.assertEqual(self.transition.title, 'Realtime enhancement')
        self.assertIsNone(self.transition._after)
        self.assertEqual(self.transition.badge.itemcget(self.transition._text, 'fill'),
                         ui_theme.tokens('light')['muted'])

    def test_theme_update_and_cancel_keep_badge_and_current_mode(self):
        transition = self.transition
        transition.begin(ui_theme.tokens('dark'), 'Realtime enhancement')
        transition.reveal()
        timer = transition._after
        transition.cancel()
        transition.apply_theme(ui_theme.tokens('light'))
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        self.assertEqual(transition.title, 'Realtime enhancement')
        self.assertEqual(transition.badge.cget('bg'), ui_theme.tokens('light')['surface'])
        self.assertEqual(transition.badge.itemcget(transition._text, 'fill'),
                         ui_theme.tokens('light')['muted'])

    def test_host_destruction_cancels_highlight(self):
        for enabled in (False, True):
            with self.subTest(animations=enabled), \
                    mock.patch('dlss5tool.workbench_transition.animations_enabled', return_value=enabled):
                host = tk.Frame(self.root)
                transition = WorkbenchTransition(
                    host, ui_theme.tokens('light'), 'Local media',
                    ('Local media', 'Realtime enhancement'))
                with mock.patch.object(host, 'winfo_ismapped', return_value=True):
                    transition.begin(ui_theme.tokens('light'), 'Realtime enhancement')
                    transition.reveal()
                timer = transition._after
                host.destroy()
                self.assertIsNone(transition._after)
                self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
