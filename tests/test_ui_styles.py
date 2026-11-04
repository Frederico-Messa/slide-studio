from __future__ import annotations

import unittest
from pathlib import Path


class WorkspaceStylesTests(unittest.TestCase):
    def test_workspace_views_and_shared_resource_styles_are_present(self) -> None:
        css = (Path(__file__).resolve().parent.parent / "static" / "style.css").read_text(encoding="utf-8")
        for selector in (
            '.preview-frame[data-mode="facts"]',
            '.preview-frame[data-mode="assets"]',
            '.preview-frame[data-mode="scripts"]',
            '.preview-frame[data-mode="recipes"]',
            '.library-workspace{height:100%',
            '.file-grid{flex:1',
            '.folder-tile,.asset-file-tile{',
            '.asset-file-tile img{',
            '.explorer-context{position:fixed',
            '.facts-table-wrap{',
            '#facts-table{border-collapse',
            '.variant-manager{display:grid',
            '.source-code-line[data-removed]::before',
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, css)


if __name__ == "__main__":
    unittest.main()
