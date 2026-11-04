from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path


class BrowserNavigationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is required to execute the JavaScript navigation tests')
    def test_navigation_in_javascript_runtime(self) -> None:
        script = Path(__file__).with_name('navigation.test.js')
        result = subprocess.run(['node', '--test', str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required to execute the JavaScript source-diff tests')
    def test_source_diff_in_javascript_runtime(self) -> None:
        script = Path(__file__).with_name('source_diff.test.js')
        result = subprocess.run(['node', '--test', str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_toast_colors_in_both_themes(self) -> None:
        root = Path(__file__).resolve().parent.parent
        theme = (root / 'static' / 'theme.css').read_text()
        style = (root / 'static' / 'style.css').read_text()
        self.assertIn('background:var(--toast-background)', style)
        self.assertIn('color:var(--toast-foreground)', style)
        self.assertIn(':root[data-theme="dark"]', theme)
        light, dark = theme.split(':root[data-theme="dark"]', 1)
        for section in (light, dark):
            self.assertIn('--toast-background:', section)
            self.assertIn('--toast-foreground:', section)
        self.assertNotIn('--toast-background: #eef0f5', dark)
        for section in (light, dark):
            colors = dict(re.findall(r'--(toast-background|toast-foreground):\s*(#[0-9a-fA-F]{6})', section))
            def luminance(hex_color: str) -> float:
                rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
                linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in rgb]
                return sum(component * weight for component, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
            levels = sorted([luminance(colors['toast-background']), luminance(colors['toast-foreground'])])
            self.assertGreaterEqual((levels[1] + 0.05) / (levels[0] + 0.05), 4.5)


if __name__ == '__main__':
    unittest.main()
