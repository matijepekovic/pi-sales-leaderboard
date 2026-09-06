#!/usr/bin/env python3
"""Architecture contract for shared visual design and Screen-owned fit."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


class ThemeLayoutEditorContractTests(unittest.TestCase):
    def test_theme_editor_uses_real_widget_renderer_and_group_save_owner(self):
        screens = (APP / "static" / "settings" / "screens.js").read_text(encoding="utf-8")
        theme = (APP / "static" / "settings" / "theme.js").read_text(encoding="utf-8")
        editor = (APP / "static" / "runtime" / "widget-renderer.js").read_text(encoding="utf-8")
        display = (APP / "static" / "display" / "app.js").read_text(encoding="utf-8")
        template = (APP / "templates" / "settings.html").read_text(encoding="utf-8")

        self.assertNotIn("StatsThemeLayoutEditor", screens)
        self.assertNotIn("data-theme-layout-auto-fit", screens)
        self.assertNotIn("StatsThemeLayoutEditor", theme)
        self.assertFalse((APP / "static" / "settings" / "theme-layout-editor.js").exists())
        self.assertIn("StatsWidgetRenderer", theme)
        self.assertIn("renderer.render", theme)
        self.assertIn("/api/widgets/preview", theme)
        self.assertIn("/appearance", theme)
        self.assertIn("Save Group Style", theme)
        self.assertIn("openTheme", theme)
        self.assertIn("widget-renderer", editor)
        self.assertLess(
            template.index("/static/runtime/widget-renderer.js"),
            template.index("/static/settings/theme.js"),
        )


if __name__ == "__main__":
    unittest.main()
