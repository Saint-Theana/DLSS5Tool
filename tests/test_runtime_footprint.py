import tempfile
import unittest
from pathlib import Path
from scripts.runtime_footprint import inventory


class FootprintTests(unittest.TestCase):
    def test_all_extensions_and_separate_editions_are_not_savings(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = [Path(directory)/name for name in ('lite', 'full')]
            for root in roots:
                root.mkdir()
                (root/'data.bin').write_bytes(b'payload')
            report = inventory(roots, min_bytes=1)
            self.assertEqual(list(report['directory_bytes'].values()), [7, 7])
            self.assertEqual(report['identical_file_candidates'][0]['copies'], 2)
            self.assertEqual(report['safe_removal_bytes'], 0)

    def test_missing_or_overlapping_roots_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                inventory([root/'missing'])
            with self.assertRaises(ValueError):
                inventory([root, root])
            with self.assertRaises(ValueError):
                inventory([root, root/'child'])
