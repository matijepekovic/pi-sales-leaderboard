"""Generic Group Types, named Groups, and Report-row membership."""
from __future__ import annotations

import uuid

from stats_core.errors import ValidationError
from stats_core.services.row_identity import infer_identity_field, infer_label_field


class GroupService:
    """Assign normalized Report rows to user-defined named Groups.

    A Group Type defines the Report and stable row identity field. Named Groups
    store only those row identities, so every current Report column flows through
    automatically after each refresh.
    """

    def __init__(self, repos, reports, themes, group_usage=None, type_usage=None):
        self.repos = repos
        self.reports = reports
        self.themes = themes
        self.group_usage = group_usage
        self.type_usage = type_usage

    @staticmethod
    def _member_key(value):
        return "" if value is None else str(value).strip()

    @classmethod
    def _member_lookup_key(cls, value):
        return cls._member_key(value).casefold()

    def list_types(self):
        groups = self.repos.groups.list()
        result = []
        for raw in self.repos.groups.list_types():
            definition = dict(raw)
            type_id = str(definition.get("id") or "")
            definition["group_count"] = sum(
                1 for group in groups if str(group.get("type_id") or "") == type_id
            )
            try:
                report_id = str(definition.get("report_id") or "")
                if not report_id:
                    definition["report_name"] = ""
                else:
                    report = self.reports.get(report_id)
                    definition["report_name"] = str(report.get("name") or report_id)
            except ValidationError:
                definition["report_name"] = "Missing Report"
            result.append(definition)
        return sorted(result, key=lambda item: str(item.get("name") or "").casefold())

    def get_type(self, type_id):
        definition = self.repos.groups.get_type(str(type_id or "").strip())
        if not definition:
            raise ValidationError("Group Type not found.")
        return dict(definition)

    def _type_fields(self, report_id):
        return {str(field.get("key") or ""): dict(field) for field in self.reports.fields(report_id)}

    def _validate_unique_field(self, report_id, field):
        seen, duplicates = set(), []
        for row in self.reports.rows(report_id):
            raw = self._member_key(row.get(field))
            if not raw:
                continue
            key = raw.casefold()
            if key in seen and raw not in duplicates:
                duplicates.append(raw)
            seen.add(key)
        if duplicates:
            sample = ", ".join(duplicates[:3])
            raise ValidationError(
                f"Some names appear more than once in '{field}' ({sample}). Use a Report with one row per member."
            )

    def _infer_member_fields(self, report_id):
        fields = self.reports.fields(report_id)
        rows = self.reports.rows(report_id)
        if not fields:
            raise ValidationError("This Report has no columns yet. Pull its data first.")
        label_field = infer_label_field(fields)
        key_field = infer_identity_field(fields, rows)
        if not key_field:
            raise ValidationError("This Report needs one unique member column before it can supply Groups.")
        return key_field, label_field or key_field

    def save_type(self, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        type_id = str(incoming.get("id") or "").strip() or f"group-type-{uuid.uuid4().hex[:12]}"
        existing = self.repos.groups.get_type(type_id) or {}
        name = str(incoming.get("name") or existing.get("name") or "").strip()[:120]
        if not name:
            raise ValidationError("Group Type name is required.")
        if any(
            str(item.get("id")) != type_id
            and str(item.get("name") or "").strip().casefold() == name.casefold()
            for item in self.repos.groups.list_types()
        ):
            raise ValidationError("A Group Type with that name already exists.")
        children = [
            item for item in self.repos.groups.list()
            if str(item.get("type_id") or "") == type_id
        ]
        report_id = str(incoming.get("report_id") or existing.get("report_id") or "").strip()
        member_key_field = str(incoming.get("member_key_field") or existing.get("member_key_field") or "").strip()
        member_label_field = str(incoming.get("member_label_field") or existing.get("member_label_field") or member_key_field).strip()
        report = None
        if report_id:
            report = self.reports.get(report_id)
            fields = self._type_fields(report_id)
            if member_key_field not in fields:
                raise ValidationError("Choose the column containing the members you want to select.")
            if member_label_field not in fields:
                member_label_field = member_key_field
            self._validate_unique_field(report_id, member_key_field)
        else:
            if children:
                raise ValidationError("This Group Type already has Groups and cannot lose its member source.")
            member_key_field = ""
            member_label_field = ""
        if children and (
            str(existing.get("report_id") or "") != report_id
            or str(existing.get("member_key_field") or "") != member_key_field
        ):
            raise ValidationError("Remove this Type's named Groups before changing its Report or name column.")
        definition = {
            "id": type_id,
            "name": name,
            "report_id": report_id,
            "member_key_field": member_key_field,
            "member_label_field": member_label_field,
            "exclusive_membership": True,
        }
        self.repos.groups.save_type(definition)
        self.repos.meta.bump("settings_version")
        return {
            **definition,
            "report_name": str((report or {}).get("name") or report_id),
            "group_count": len(children),
        }

    def delete_type(self, type_id):
        definition = self.get_type(type_id)
        used_by = list(self.type_usage(type_id) if self.type_usage else [])
        if used_by:
            raise ValidationError(f"This Group Type is used by {used_by[0]}. Change that item first.")
        if any(str(group.get("type_id") or "") == str(type_id) for group in self.repos.groups.list()):
            raise ValidationError("Delete this Type's named Groups first.")
        if not self.repos.groups.delete_type(type_id):
            raise ValidationError("Group Type not found.")
        self.repos.meta.bump("settings_version")
        return definition

    def _enrich(self, raw):
        group = dict(raw)
        definition = self.repos.groups.get_type(group.get("type_id")) or {}
        group["type_name"] = str(definition.get("name") or "Missing Group Type")
        group["report_id"] = str(definition.get("report_id") or "")
        group["member_key_field"] = str(definition.get("member_key_field") or "")
        group["member_label_field"] = str(definition.get("member_label_field") or "")
        group["exclusive_membership"] = True
        group["member_count"] = len(group.get("member_keys") or [])
        group["roles"] = self._roles_from_saved(group)
        self._set_legacy_leader(group)
        group["appearance"] = self.appearance(group["id"])
        return group

    @staticmethod
    def _roles_from_saved(group):
        if isinstance(group.get("roles"), list):
            return [dict(role) for role in group["roles"] if isinstance(role, dict)]
        if group.get("leader_member_key") or group.get("leader_title"):
            return [{"id": "role-leader", "name": str(group.get("leader_title") or "Team Lead"),
                     "member_key": str(group.get("leader_member_key") or "")}]
        return []

    @staticmethod
    def _set_legacy_leader(group):
        """Existing leader Fields use the first role until their binding is edited."""
        first = next(iter(group.get("roles") or []), {})
        group["leader_title"] = str(first.get("name") or "Team Lead")
        group["leader_member_key"] = str(first.get("member_key") or "")

    def _clean_roles(self, raw, member_keys):
        if not isinstance(raw, list):
            raise ValidationError("Roles must be a list.")
        members = {self._member_lookup_key(key): key for key in member_keys}
        roles, ids, names = [], set(), set()
        for item in raw:
            if not isinstance(item, dict):
                raise ValidationError("Each role needs a name and a selected member.")
            name = str(item.get("name") or "").strip()[:80]
            if not name:
                raise ValidationError("Role name is required.")
            if name.casefold() in names:
                raise ValidationError("Role names must be unique within this Group.")
            role_id = str(item.get("id") or "").strip() or f"role-{uuid.uuid4().hex[:12]}"
            if role_id in ids:
                raise ValidationError("Each role must have a unique ID.")
            lookup = self._member_lookup_key(item.get("member_key"))
            if lookup and lookup not in members:
                raise ValidationError("Role holders must be selected Group members.")
            roles.append({"id": role_id, "name": name, "member_key": members.get(lookup, "")})
            ids.add(role_id)
            names.add(name.casefold())
        return roles

    def appearance(self, group_id):
        group = self.repos.groups.get(str(group_id or "").strip())
        if not group:
            raise ValidationError("Group not found.")
        raw = group.get("appearance")
        return dict(raw) if isinstance(raw, dict) else self.themes.legacy_group_appearance(group_id)

    def save_appearance(self, group_id, incoming):
        group = self.repos.groups.get(str(group_id or "").strip())
        if not group:
            raise ValidationError("Group not found.")
        current = self.appearance(group_id)
        incoming = incoming if isinstance(incoming, dict) else {}
        # The existing Theme Editor route sends resolved visual keys. Keep that
        # active contract while all Group choices persist with the Group owner.
        if "style" not in incoming:
            style = dict(current.get("style") or {})
            for key in ("colors", "corner_settings", "hero_scale", "row_stripe"):
                if key in incoming:
                    style[key] = incoming[key]
            incoming = {**incoming, "style": style}
            if "base" in incoming and "theme_id" not in incoming:
                incoming["theme_id"] = incoming["base"]
        appearance = self.themes.clean_group_appearance({**current, **incoming})
        group["appearance"] = appearance
        self.repos.groups.save(group)
        version = self.repos.meta.bump("settings_version")
        return version, self.themes.resolve_appearance(appearance, group_id)

    def reset_appearance(self, group_id):
        return self.save_appearance(group_id, {"theme_id": "starter", "asset_bindings": {}, "style": {}, "widget_styles": {}})

    def apply_asset(self, group_id, asset_key, upload=None, library_id=None):
        appearance = self.appearance(group_id)
        reference = self.themes.asset_reference(asset_key, upload, library_id)
        bindings = {**appearance.get("asset_bindings", {}), asset_key: reference}
        return self.save_appearance(group_id, {"asset_bindings": bindings})

    def reset_asset(self, group_id, asset_key):
        appearance = self.appearance(group_id)
        bindings = dict(appearance.get("asset_bindings") or {})
        bindings.pop(asset_key, None)
        return self.save_appearance(group_id, {"asset_bindings": bindings})

    def theme_references(self, theme_id):
        return [str(group.get("name") or group["id"]) for group in self.repos.groups.list()
                if str(self.appearance(group["id"]).get("theme_id")) == str(theme_id)]

    def asset_references(self, asset_id):
        return [str(group.get("name") or group["id"]) for group in self.repos.groups.list()
                if asset_id in (self.appearance(group["id"]).get("asset_bindings") or {}).values()]

    def widget_references(self, widget_id):
        return [str(group.get("name") or group["id"]) for group in self.repos.groups.list()
                if str(widget_id) in (self.appearance(group["id"]).get("widget_styles") or {})]

    def list(self, type_id=None):
        rows = self.repos.groups.list()
        if type_id:
            rows = [row for row in rows if str(row.get("type_id") or "") == str(type_id)]
        return sorted(
            (self._enrich(row) for row in rows),
            key=lambda item: (str(item.get("type_name") or "").casefold(), str(item.get("name") or "").casefold()),
        )

    def get(self, group_id):
        group = self.repos.groups.get(str(group_id or "").strip())
        if not group:
            raise ValidationError("Group not found.")
        return self._enrich(group)

    def rows_for_type(self, type_id, report_id=None, member_field=None):
        definition = self.get_type(type_id)
        configured_report_id = str(definition.get("report_id") or "")
        configured_field = str(definition.get("member_key_field") or "")
        report_id = str(report_id or configured_report_id).strip()
        key_field = str(member_field or configured_field).strip()
        label_field = str(definition.get("member_label_field") or key_field).strip()
        if not report_id:
            raise ValidationError("Choose a Report containing the members.")
        if not key_field:
            key_field, label_field = self._infer_member_fields(report_id)
        fields = self._type_fields(report_id)
        if key_field not in fields:
            raise ValidationError("Choose a valid member column.")
        children = self.repos.groups.list()
        children = [item for item in children if str(item.get("type_id") or "") == str(type_id)]
        if children and (report_id != configured_report_id or key_field != configured_field):
            raise ValidationError("This Group Type already uses a different member list.")
        definition = {
            **definition,
            "report_id": report_id,
            "member_key_field": key_field,
            "member_label_field": label_field,
        }
        groups = self.list(type_id)
        membership = {}
        for group in groups:
            for value in group.get("member_keys") or []:
                membership.setdefault(self._member_lookup_key(value), []).append({"id": group["id"], "name": group["name"]})
        rows = []
        for source in self.reports.rows(report_id):
            row = dict(source)
            key = self._member_key(row.get(key_field))
            if not key:
                continue
            row["_stats_member_key"] = key
            row["_stats_groups"] = membership.get(key.casefold(), [])
            rows.append(row)
        return {
            "type": {**definition, "report_name": str(self.reports.get(report_id).get("name") or report_id)},
            "fields": self.reports.fields(report_id),
            "rows": rows,
        }

    def save(self, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        group_id = str(incoming.get("id") or "").strip() or f"group-{uuid.uuid4().hex[:12]}"
        existing = self.repos.groups.get(group_id) or {}
        type_id = str(incoming.get("type_id") or existing.get("type_id") or "").strip()
        definition = self.get_type(type_id)
        if not definition.get("report_id") or not definition.get("member_key_field"):
            report_id = str(incoming.get("report_id") or "").strip()
            member_field = str(incoming.get("member_field") or "").strip()
            if report_id and not member_field:
                member_field, member_label_field = self._infer_member_fields(report_id)
            else:
                member_label_field = member_field
            definition = self.save_type({
                **definition,
                "report_id": report_id,
                "member_key_field": member_field,
                "member_label_field": member_label_field,
                "exclusive_membership": True,
            })
        name = str(incoming.get("name") or existing.get("name") or "").strip()[:120]
        if not name:
            raise ValidationError("Group name is required.")
        if any(
            str(item.get("id")) != group_id
            and str(item.get("type_id") or "") == type_id
            and str(item.get("name") or "").strip().casefold() == name.casefold()
            for item in self.repos.groups.list()
        ):
            raise ValidationError("This Group Type already has a Group with that name.")
        available = {
            self._member_lookup_key(row.get("_stats_member_key")): self._member_key(row.get("_stats_member_key"))
            for row in self.rows_for_type(type_id)["rows"]
        }
        # A temporary absent row does not erase an existing membership on save.
        for key in existing.get("member_keys") or []:
            available.setdefault(self._member_lookup_key(key), self._member_key(key))
        source_members = incoming.get("member_keys") if isinstance(incoming.get("member_keys"), list) else existing.get("member_keys", [])
        member_keys, seen = [], set()
        for value in source_members:
            lookup = self._member_lookup_key(value)
            if not lookup or lookup in seen or lookup not in available:
                continue
            seen.add(lookup)
            member_keys.append(available[lookup])
        raw_roles = incoming.get("roles", self._roles_from_saved(existing))
        if "roles" not in incoming:
            raw_roles = [{**role, "member_key": role.get("member_key") if self._member_lookup_key(role.get("member_key")) in seen else ""} for role in raw_roles]
        if "roles" not in incoming and ("leader_title" in incoming or "leader_member_key" in incoming):
            first = dict(next(iter(raw_roles), {}))
            first.update({"id": first.get("id") or "role-leader",
                          "name": incoming.get("leader_title", first.get("name") or "Team Lead"),
                          "member_key": incoming.get("leader_member_key", first.get("member_key") or "")})
            if self._member_lookup_key(first.get("member_key")) not in seen:
                first["member_key"] = ""
            raw_roles = [first, *raw_roles[1:]]
        roles = self._clean_roles(raw_roles, member_keys)
        saved = {
            **existing,
            "id": group_id,
            "type_id": type_id,
            "name": name,
            "member_keys": member_keys,
            "roles": roles,
        }
        self._set_legacy_leader(saved)
        if "appearance" in incoming:
            saved["appearance"] = self.themes.clean_group_appearance(incoming["appearance"])
        all_groups = [dict(item) for item in self.repos.groups.list()]
        if seen:
            for sibling in all_groups:
                if str(sibling.get("id")) == group_id or str(sibling.get("type_id") or "") != type_id:
                    continue
                sibling["member_keys"] = [
                    value for value in sibling.get("member_keys") or []
                    if self._member_lookup_key(value) not in seen
                ]
                sibling["roles"] = self._roles_from_saved(sibling)
                for role in sibling["roles"]:
                    if self._member_lookup_key(role.get("member_key")) in seen:
                        role["member_key"] = ""
                self._set_legacy_leader(sibling)
        all_groups = [item for item in all_groups if str(item.get("id")) != group_id]
        all_groups.append(saved)
        self.repos.groups.save_all(all_groups)
        self.repos.meta.bump("settings_version")
        return self.get(group_id)

    def dataset(self, group_id):
        group = self.get(group_id)
        definition = self.get_type(group.get("type_id"))
        report_id = str(definition.get("report_id") or "")
        key_field = str(definition.get("member_key_field") or "")
        selected = {self._member_lookup_key(value) for value in group.get("member_keys") or []}
        rows = [
            dict(row) for row in self.reports.rows(report_id)
            if self._member_lookup_key(row.get(key_field)) in selected
        ]
        return {
            "group": group,
            "type": definition,
            "report": self.reports.get(report_id),
            "fields": self.reports.fields(report_id),
            "rows": rows,
        }

    def group_for_row(self, type_id, row):
        definition = self.get_type(type_id)
        key = self._member_lookup_key((row or {}).get(definition.get("member_key_field")))
        if not key:
            return None
        for group in self.list(type_id):
            if key in {self._member_lookup_key(value) for value in group.get("member_keys") or []}:
                return group
        return None

    def delete(self, group_id):
        group = self.get(group_id)
        used_by = list(self.group_usage(group_id) if self.group_usage else [])
        if used_by:
            raise ValidationError(f"This Group is used by {used_by[0]}. Change that item first.")
        self.themes.purge_group_theme(group_id)
        self.repos.groups.delete(group_id)
        self.repos.meta.bump("settings_version")
        return group
