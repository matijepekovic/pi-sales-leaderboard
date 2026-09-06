"""Frontend boundaries for Field-based Widgets and Screen instance composition."""
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parent.parent


class WidgetFrontendContractTests(unittest.TestCase):
    def test_builder_uses_field_ids_and_shared_preview(self):
        source = (ROOT / "app/static/settings/widgets.js").read_text(encoding="utf-8")
        self.assertIn("/api/fields/catalog", source)
        self.assertIn("field_ids", source)
        self.assertIn("Preview in Theme Editor", source)
        self.assertIn("/api/widgets/preview", source)
        for forbidden in ("/api/data/reports", "source_id", "report_id", "sample_rows"):
            self.assertNotIn(forbidden, source)

    def test_builder_keeps_context_guidance_and_global_owners_explicit(self):
        source = (ROOT / "app/static/settings/widgets.js").read_text(encoding="utf-8")
        for required in ("measure_settings", "ratio_mode", "result_type", "StatsFields.openMatching",
                         "Edit Field globally", "last verified result", "requestVersion",
                         "updateColumn", "fingerprint", "Undo"):
            self.assertIn(required, source)
        for obsolete in ("widget-builder-step", "widget-visualizations", "recommendRoles", "summaryExplicit"):
            self.assertNotIn(obsolete, source)
        self.assertNotIn("/api/fields/matches", source)
        self.assertNotIn("timeframe:", source)

    def test_screen_composes_instances_and_display_cannot_scroll(self):
        screens = (ROOT / "app/static/settings/screens.js").read_text(encoding="utf-8")
        display_css = (ROOT / "app/static/display/app.css").read_text(encoding="utf-8")
        renderer_css = (ROOT / "app/static/runtime/widget-renderer.css").read_text(encoding="utf-8")
        self.assertIn("widget_id", screens)
        self.assertIn("data-instance-move", screens)
        self.assertIn("data-instance-resize", screens)
        self.assertIn("Show rows", screens)
        self.assertNotIn("/api/table-presets", screens)
        self.assertNotIn("data-report=", screens)
        assets = (ROOT / "app/static/settings/screen-assets.js").read_text(encoding="utf-8")
        self.assertIn("StatsScreenAssets", screens)
        self.assertIn("data-screen-asset-move", assets)
        self.assertIn("data-screen-asset-resize", assets)
        self.assertNotIn("/api/asset-library", assets)
        self.assertNotIn("/api/themes", assets)
        self.assertNotRegex(display_css + renderer_css, r"overflow(?:-x|-y)?:\s*(?:auto|scroll)")

    def test_previews_and_display_share_renderer_and_value_contract(self):
        for template in ("settings.html", "display.html"):
            content = (ROOT / "app/templates" / template).read_text(encoding="utf-8")
            self.assertIn("/static/runtime/field-values.js", content)
            self.assertIn("/static/runtime/widget-charts.js", content)
            self.assertIn("/static/runtime/widget-renderer.js", content)
        for script in ("app/static/settings/widgets.js", "app/static/settings/screens.js", "app/static/display/app.js"):
            self.assertIn("StatsWidgetRenderer", (ROOT / script).read_text(encoding="utf-8"))

    def test_chart_rendering_is_shared_and_does_not_aggregate_source_rows(self):
        charts = (ROOT / "app/static/runtime/widget-charts.js").read_text(encoding="utf-8")
        renderer = (ROOT / "app/static/runtime/widget-renderer.js").read_text(encoding="utf-8")
        self.assertIn("StatsWidgetCharts.render", renderer)
        self.assertNotIn("stroke-dasharray", renderer)
        self.assertIn("percentage_scale", charts)
        self.assertIn("pie_mode", charts)
        for forbidden in ("/api/", "section.rows", "report_id", "source_id"):
            self.assertNotIn(forbidden, charts)

    @unittest.skipUnless(shutil.which("node"), "Node is required for renderer behavior checks")
    def test_renderer_behavior(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "windows/test_widget_frontend.js")], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node is required for builder behavior checks")
    def test_guided_builder_and_preview_validation(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "windows/test_widget_builder.js")], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node is required for selection behavior checks")
    def test_field_selection_keeps_picker_and_preview_stable(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "windows/test_widget_selection.js")], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_inline_formula_has_one_owner_and_no_frontend_math_engine(self):
        ui = (ROOT / "app/static/settings/field-formulas.js").read_text(encoding="utf-8")
        builder = (ROOT / "app/static/settings/widgets.js").read_text(encoding="utf-8")
        self.assertIn("StatsFieldFormulas.open", builder)
        self.assertIn("/api/fields/", ui)
        self.assertNotIn("/api/widgets", ui)
        self.assertNotIn("eval(", ui)
        self.assertNotIn("new Function", ui)
        self.assertNotIn("data-widget-calculation-field", builder)
        self.assertIn('editableFields:"context"', builder)
        self.assertIn("Show as:", builder)
        self.assertIn("resultPayload", builder)
        for obsolete in ("widget-results-grid", "calculation_preview", "widget-calculation-option",
                         "refreshCalculations", "data-widget-outcomes", "data-widget-underlying",
                         "data-context-field-editor", "filtersOpen", "S.intent"):
            self.assertNotIn(obsolete, builder)

    @unittest.skipUnless(shutil.which("node"), "Node is required for formula behavior checks")
    def test_inline_formula_behavior(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "windows/test_field_formula_editor.js")], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
