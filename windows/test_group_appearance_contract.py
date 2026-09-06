"""Group-owned choices resolve through Theme APIs with isolated stored data."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from flask import Flask
from werkzeug.datastructures import FileStorage


class Reports:
    def fields(self, report_id):
        return [{"key": "Name", "label": "Name", "type": "text"}, {"key": "Net", "label": "Net", "type": "number"}]

    def rows(self, report_id):
        return [{"Name": "Alex", "Net": 10}, {"Name": "Blair", "Net": 20}]

    def get(self, report_id):
        return {"id": report_id, "name": "Sales"}


class GroupAppearanceContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data_dir = os.environ.get("STATS_DATA_DIR")
        os.environ["STATS_DATA_DIR"] = self.temp.name
        from stats_core.repositories import Repositories
        from stats_core.services.groups import GroupService
        from stats_core.theme.service import ThemeService
        from stats_core.theme.web import blueprint
        self.repos = Repositories(data_root=self.temp.name)
        self.theme = ThemeService(self.repos, group_context=lambda key: self.groups.appearance(key),
                                  theme_usage=lambda key: self.groups.theme_references(key),
                                  asset_usage=lambda key: self.groups.asset_references(key))
        self.groups = GroupService(self.repos, Reports(), self.theme)
        self.kind = self.groups.save_type({"name": "Teams", "report_id": "report-a", "member_key_field": "Name"})
        self.group = self.groups.save({"type_id": self.kind["id"], "name": "North", "member_keys": ["Alex", "Blair"]})
        self.app = Flask(__name__)
        self.app.register_blueprint(blueprint(self.theme, self.groups))
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()
        if self.old_data_dir is None:
            os.environ.pop("STATS_DATA_DIR", None)
        else:
            os.environ["STATS_DATA_DIR"] = self.old_data_dir

    def test_named_theme_changes_propagate_with_group_style_priority(self):
        theme = self.theme.save_theme({"name": "Ocean", "colors": {"primary": "#0000ff", "text": "#dddddd"}})
        self.groups.save_appearance(self.group["id"], {"theme_id": theme["id"], "style": {"colors": {"primary": "#ff0000"}}})
        self.theme.save_theme({"id": theme["id"], "colors": {"primary": "#00ff00", "text": "#ffffff"}})
        result = self.theme.effective_group_theme(self.group["id"])
        self.assertEqual(result["colors"]["primary"], "#ff0000")
        self.assertEqual(result["colors"]["text"], "#ffffff")
        self.assertEqual(self.repos.groups.get(self.group["id"])["appearance"]["theme_id"], theme["id"])
        self.assertEqual(self.repos.themes.get_group(self.group["id"]), {})
        self.groups.save({"id": self.group["id"], "name": "Renamed"})
        self.assertEqual(self.groups.appearance(self.group["id"])["theme_id"], theme["id"])

    def test_roles_are_named_and_member_constrained(self):
        result = self.groups.save({"id": self.group["id"], "roles": [
            {"name": "Manager", "member_key": "Alex"}, {"name": "Right hand", "member_key": "Blair"}]})
        self.assertEqual(result["leader_member_key"], "Alex")
        self.assertEqual(result["leader_title"], "Manager")
        ids = [role["id"] for role in result["roles"]]
        self.assertEqual(len(set(ids)), 2)
        with self.assertRaisesRegex(ValueError, "selected Group members"):
            self.groups.save({"id": self.group["id"], "roles": [{"name": "Manager", "member_key": "Unknown"}]})
        self.groups.save({"type_id": self.kind["id"], "name": "South", "member_keys": ["Alex"]})
        moved = self.groups.get(self.group["id"])
        self.assertEqual(moved["roles"][0]["member_key"], "")
        self.assertEqual(moved["roles"][1]["member_key"], "Blair")
        self.assertEqual([role["id"] for role in moved["roles"]], ids)

    def test_legacy_group_appearance_and_asset_are_preserved(self):
        key = self.group["id"]
        self.repos.themes.save_group(key, {"base": "classic", "colors": {"primary": "#123456"}, "assets": {"logo_small": "logo_small.png"}})
        upload = FileStorage(stream=io.BytesIO(b"legacy-artwork"), filename="logo.png")
        self.repos.applied_assets.save_upload(f"group-{key}", "logo_small", upload, ".png")
        result = self.theme.effective_group_theme(key)
        self.assertEqual(result["colors"]["primary"], "#123456")
        self.assertIn(f"/api/group-theme-assets/{key}/logo_small", result["assets"]["logo_small"])
        self.groups.save_appearance(key, {"style": {"colors": {"text": "#ffffff"}}})
        self.assertEqual(self.theme.group_asset_path(key, "logo_small").read_bytes(), b"legacy-artwork")
        self.assertEqual(self.repos.themes.get_group(key)["colors"]["primary"], "#123456")

    def test_group_theme_facade_writes_group_owner_and_cannot_change_canvas(self):
        before = self.repos.themes.get_layout()
        response = self.client.put(f"/api/group-themes/{self.group['id']}", json={"colors": {"primary": "#234567"}, "layout": {"content": {"width": 50}}})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.groups.appearance(self.group["id"])["style"]["colors"]["primary"], "#234567")
        self.assertEqual(self.repos.themes.get_layout(), before)
        self.assertEqual(self.repos.themes.get_group(self.group["id"]), {})

    def test_reusable_theme_copy_keeps_legacy_artwork(self):
        key = self.group["id"]
        upload = FileStorage(stream=io.BytesIO(b"custom-artwork"), filename="logo.png")
        self.repos.applied_assets.save_upload(f"group-{key}", "logo_small", upload, ".png")
        self.repos.themes.save_group(key, {"assets": {"logo_small": "logo_small.png"}})
        theme = self.theme.save_theme({"name": "Copy", "copy_from": {"owner": "group", "id": key},
                                       "asset_bindings": self.groups.appearance(key)["asset_bindings"]})
        reference = theme["asset_bindings"]["logo_small"]
        self.assertTrue(reference.startswith("user:"))
        self.assertEqual(self.theme.library_item_path("logo_small", reference[5:]).read_bytes(), b"custom-artwork")

    def test_group_and_type_deletions_use_injected_consumers(self):
        self.groups.group_usage = lambda _key: ["Office Screen"]
        with self.assertRaisesRegex(ValueError, "Office Screen"):
            self.groups.delete(self.group["id"])
        self.groups.type_usage = lambda _key: ["Logo Field"]
        with self.assertRaisesRegex(ValueError, "Logo Field"):
            self.groups.delete_type(self.kind["id"])

    def test_deletion_reports_theme_and_asset_consumers(self):
        theme = self.theme.save_theme({"name": "Referenced Theme"})
        self.groups.save_appearance(self.group["id"], {"theme_id": theme["id"]})
        response = self.client.delete(f"/api/themes/{theme['id']}")
        self.assertEqual(response.status_code, 400)
        self.assertIn("North", response.get_json()["error"])
        upload = FileStorage(stream=io.BytesIO(b"asset-data"), filename="logo.png")
        self.groups.apply_asset(self.group["id"], "logo_small", upload=upload)
        reference = self.groups.appearance(self.group["id"])["asset_bindings"]["logo_small"]
        with self.assertRaisesRegex(ValueError, "North"):
            self.theme.delete_library_item("logo_small", reference[5:])
        self.groups.reset_asset(self.group["id"], "logo_small")
        self.theme.delete_library_item("logo_small", reference[5:])
        self.groups.reset_appearance(self.group["id"])
        self.theme.delete_theme(theme["id"])

    def test_widget_refinements_cannot_change_data_logic(self):
        with self.assertRaisesRegex(ValueError, "visual settings only"):
            self.groups.save_appearance(self.group["id"], {"widget_styles": {"widget-a": {"filters": []}}})
        self.groups.save_appearance(self.group["id"], {"widget_styles": {"widget-a": {"font_size": 24, "padding": 0}}})
        self.assertEqual(self.theme.effective_group_theme(self.group["id"])["widget_styles"]["widget-a"]["padding"], 0)

    def test_theme_does_not_access_group_repository(self):
        source = (ROOT / "app" / "stats_core" / "theme" / "service.py").read_text(encoding="utf-8")
        self.assertNotIn("repos.groups", source)
        self.assertNotIn("repos.screens", source)


if __name__ == "__main__":
    unittest.main()
