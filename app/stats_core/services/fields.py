"""Global Field catalog over normalized Reports, Groups, and table context."""
from __future__ import annotations

import ast
import json
import operator
import re
import uuid

from stats_core.errors import ValidationError
from stats_core.services.field_matching import (
    full_outer, match_key, numeric_value, public_row_key, relationship_path, unique_index,
)
from stats_core.theme.catalog import ASSETS


_FIELD_TOKEN = re.compile(r"\[([^\[\]]+)\]")
_CALCULATED_TYPES = {"number", "percent", "text"}
_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class FieldService:
    """Own every Field users can place into a Screen table.

    Report field identity remains owned by the Report snapshot. This service
    composes those fields with Report-owned calculations, Group lookups, and
    table-generated values without teaching Reports about Groups or Screens.
    """

    RANK_KEY = "__stats_rank"

    def __init__(self, repos, reports, groups, themes, dependencies=None, period_rows=None, matching_consumers=None):
        self.repos = repos
        self.reports = reports
        self.groups = groups
        self.themes = themes
        self.dependencies = dependencies
        self.period_rows = period_rows
        self.matching_consumers = matching_consumers

    @staticmethod
    def field_id(report_id, field_key):
        """Stable public identity independent of user-editable display labels."""
        identity = json.dumps([str(report_id), str(field_key)], separators=(",", ":"))
        return f"field-{uuid.uuid5(uuid.NAMESPACE_URL, 'stats:field:' + identity).hex}"

    def ids_for_report(self, report_id, keys):
        available = {str(field["key"]): field["id"] for field in self.fields(report_id)}
        result = []
        for key in keys or []:
            if str(key) not in available:
                raise ValidationError(f"Field '{key}' is unavailable. Update its references first.")
            result.append(available[str(key)])
        return result

    def catalog_all(self):
        """Browse by Report without making consumers choose their data input."""
        return [
            {"id": report["id"], "name": str(report.get("name") or report["id"]),
             "fields": self.fields(report["id"])}
            for report in self.reports.list()
        ]

    def group_type_references(self, type_id):
        """Expose Field dependencies without giving Groups access to Field storage."""
        names = []
        for report in self.reports.list():
            for field in self.fields(report["id"]):
                if str(field.get("group_type_id") or "") == str(type_id):
                    names.append(str(field.get("label") or field["id"]))
        return names

    def report_dependency_ids(self, report_id):
        return [field["id"] for field in self.fields(report_id)]

    def _resolve_ids(self, field_ids, require_matching=True):
        if not isinstance(field_ids, list) or not field_ids:
            raise ValidationError("Choose at least one Field.")
        requested = list(dict.fromkeys(str(value) for value in field_ids))
        resolved = {}
        for report in self.reports.list():
            report_id = str(report["id"])
            for field in self.fields(report_id):
                if field["id"] in requested:
                    resolved[field["id"]] = (report_id, field)
        missing = [value for value in requested if value not in resolved]
        if missing:
            raise ValidationError(f"Field '{missing[0]}' is unavailable. Update its references first.")
        result = [resolved[value] for value in requested]
        if require_matching:
            self._matching_plan(list(dict.fromkeys(report_id for report_id, _ in result)))
        return result

    def _matching_edges(self, rules=None):
        edges = []
        for rule in self.repos.fields.matching_rules() if rules is None else rules:
            try:
                left, right = self._resolve_ids([rule["left_field_id"], rule["right_field_id"]], False)
            except (KeyError, ValidationError):
                continue
            edges.append({**rule, "left_report": left[0], "left_field": left[1],
                          "right_report": right[0], "right_field": right[1]})
        return edges

    def _matching_plan(self, report_ids):
        if len(report_ids) < 2:
            return []
        edges, plan = self._matching_edges(), []
        for report_id in report_ids[1:]:
            path = relationship_path(report_ids[0], report_id, edges)
            if path is None:
                raise ValidationError("These Fields do not share a dataset or a saved row match. Define matching in Fields before combining them.")
            for edge in path:
                if edge["id"] not in {item["id"] for item in plan}:
                    plan.append(edge)
        return plan

    @staticmethod
    def _public_field(field):
        result = {name: field[name] for name in ("id", "label", "type", "decimals", "kind", "formula", "description") if name in field}
        if field.get("type") == "percent":
            result["percent_input_scale"] = field.get("percent_input_scale", "auto")
        result["key"] = field["id"]
        return result

    def resolve(self, field_ids):
        return [self._public_field(field) for _, field in self._resolve_ids(field_ids)]

    def identity_fields(self, field_ids):
        """Eligible explicit row identities, never a name-based identity guess."""
        reports = {report_id for report_id, _ in self._resolve_ids(field_ids, False)}
        return [self._public_field(field) for report_id in sorted(reports) for field in self.fields(report_id)
                if field.get("kind") == "report" and field.get("type") in {"text", "number"}]

    def compatibility(self, field_ids):
        """Read-only guidance, supplied by Fields rather than re-created by Widgets."""
        resolved = self._resolve_ids(field_ids, False)
        try:
            plan = self._matching_plan(list(dict.fromkeys(report_id for report_id, _ in resolved)))
        except ValidationError as exc:
            return {"compatible": False, "status": "matching_required", "message": str(exc), "matching_rules": []}
        try:
            result = self.evaluate(field_ids) if plan else {}
        except ValidationError as exc:
            return {"compatible": False, "status": "ambiguous_rows", "message": str(exc),
                    "matching_rules": [edge["id"] for edge in plan]}
        return {"compatible": True, "status": "ready", "message": "", "matching_rules": [edge["id"] for edge in plan],
                "matching": result.get("matching", {})}

    def matching_rules(self):
        result = []
        for rule in self.repos.fields.matching_rules():
            item = dict(rule)
            try:
                left, right = self._resolve_ids([rule["left_field_id"], rule["right_field_id"]], False)
                item["left"] = {"report": {"id": left[0], "name": self.reports.get(left[0]).get("name")},
                                "field": self._public_field(left[1])}
                item["right"] = {"report": {"id": right[0], "name": self.reports.get(right[0]).get("name")},
                                 "field": self._public_field(right[1])}
                item["status"] = "ready"
            except (KeyError, ValidationError):
                item["status"] = "missing_field"
            result.append(item)
        return result

    def _matching_definition(self, incoming, rule_id=""):
        if not isinstance(incoming, dict):
            raise ValidationError("Choose the two Fields whose values match.")
        ids = [str(incoming.get(side) or "") for side in ("left_field_id", "right_field_id")]
        if not all(ids) or ids[0] == ids[1]:
            raise ValidationError("Choose a matching Field from each Report.")
        left, right = self._resolve_ids(ids, False)
        if left[0] == right[0]:
            raise ValidationError("A saved row match connects Fields from different Reports.")
        if any(field.get("kind") != "report" or field.get("type") not in {"text", "number"} for _, field in (left, right)):
            raise ValidationError("Match using an existing text or number Report Field, not a calculated or generated value.")
        if left[1]["type"] != right[1]["type"]:
            raise ValidationError("The matching Fields must both be text or both be numbers. Change their definitions in Fields if needed.")
        edges = self._matching_edges([rule for rule in self.repos.fields.matching_rules() if rule["id"] != rule_id])
        if relationship_path(left[0], right[0], edges) is not None:
            raise ValidationError("These Reports already have a saved matching path. Use or edit that rule instead of creating an ambiguous second path.")
        name = str(incoming.get("name") or "").strip()[:120]
        if not name:
            name = f"{self.reports.get(left[0]).get('name') or left[0]} ↔ {self.reports.get(right[0]).get('name') or right[0]}"[:120]
        return {"id": rule_id or f"match-{uuid.uuid4().hex[:12]}", "name": name,
                "left_field_id": ids[0], "right_field_id": ids[1],
                "mode": "one_to_one", "unmatched": "keep", "text_comparison": "trimmed_exact"}, left, right

    def preview_matching(self, incoming, rule_id=""):
        """Inspect cached real rows; no source refresh or persistence during preview."""
        rule, left, right = self._matching_definition(incoming, rule_id)
        left_rows, right_rows = self.reports.rows(left[0]), self.reports.rows(right[0])
        pairs, counts = full_outer(left_rows, right_rows,
            lambda row: match_key(row.get(left[1]["key"]), left[1]["type"]),
            lambda row: match_key(row.get(right[1]["key"]), right[1]["type"]), left[1]["label"], right[1]["label"])
        return {"rule": rule, "counts": counts,
                "rows": [{"left": a.get(left[1]["key"]) if a else None,
                          "right": b.get(right[1]["key"]) if b else None,
                          "status": "matched" if a is not None and b is not None else "left_only" if a is not None else "right_only"}
                         for a, b in pairs],
                "message": "Every unmatched row is kept. Blank matching values do not match each other."}

    def save_matching(self, incoming, rule_id=""):
        existing = next((rule for rule in self.repos.fields.matching_rules() if rule["id"] == rule_id), None) if rule_id else None
        if rule_id and existing is None:
            raise ValidationError("Matching rule not found.")
        if existing and any(str(incoming.get(key) or "") != existing[key] for key in ("left_field_id", "right_field_id")):
            used_by = self._matching_dependents(rule_id)
            if used_by:
                raise ValidationError(f"This row match is used by {used_by[0]}. Remove or replace its dependent Fields there before changing the match.")
        rule = self.preview_matching(incoming, rule_id)["rule"]
        self.repos.fields.save_matching_rule(rule)
        self.repos.meta.bump("settings_version")
        return rule

    def matching_field_references(self, field_id):
        return [f"row match '{rule['name']}'" for rule in self.repos.fields.matching_rules()
                if str(field_id) in (rule.get("left_field_id"), rule.get("right_field_id"))]

    def _matching_dependents(self, rule_id):
        if self.matching_consumers:
            used_by = []
            for consumer in self.matching_consumers():
                try:
                    resolved = self._resolve_ids(consumer.get("field_ids") or [], False)
                    plan = self._matching_plan(list(dict.fromkeys(report_id for report_id, _ in resolved)))
                except ValidationError:
                    continue
                if rule_id in {edge["id"] for edge in plan}:
                    used_by.append(str(consumer.get("name") or "a saved Widget placement"))
            return list(dict.fromkeys(used_by))
        if not self.dependencies:
            return []
        consumers = {}
        for report in self.reports.list():
            for field in self.fields(report["id"]):
                for consumer in self.dependencies(field["id"]) or []:
                    consumers.setdefault(consumer, set()).add(str(report["id"]))
        used_by = []
        for consumer, reports in consumers.items():
            try:
                plan = self._matching_plan(sorted(reports))
            except ValidationError:
                continue
            if rule_id in {edge["id"] for edge in plan}:
                used_by.append(consumer)
        return used_by

    def delete_matching(self, rule_id):
        used_by = self._matching_dependents(rule_id)
        if used_by:
            raise ValidationError(f"This row match is used by {used_by[0]}. Remove its dependent Fields there first.")
        if not self.repos.fields.delete_matching_rule(str(rule_id)):
            raise ValidationError("Matching rule not found.")
        self.repos.meta.bump("settings_version")

    def evaluate(self, field_ids, context=None):
        """Supply normalized ID-keyed values; source lineage stays inside Fields."""
        context = context if isinstance(context, dict) else {}
        resolved = self._resolve_ids(field_ids)
        report_ids = list(dict.fromkeys(report_id for report_id, _ in resolved))
        plan = self._matching_plan(report_ids)
        identity_id = str(context.get("identity_field_id") or "")
        identity = self._resolve_ids([identity_id], False)[0] if identity_id else None
        if identity:
            if identity[0] not in report_ids or identity[1].get("kind") != "report" or identity[1].get("type") not in {"text", "number"}:
                raise ValidationError("Choose a Report text or number Field from this selection to match rows across periods.")
        group_ids = context.get("group_ids") or []
        self.validate_scope(field_ids, group_ids)
        timeframe = context.get("timeframe")
        all_reports = list(dict.fromkeys([*report_ids, *[edge[side] for edge in plan for side in ("left_report", "right_report")]]))
        sources = {}
        for report_id in all_reports:
            if timeframe is not None:
                if self.period_rows is None:
                    raise ValidationError("Custom timeframes are not available for this data connection yet.")
                raw_rows = self.period_rows(report_id, timeframe)
            else:
                raw_rows = self.reports.rows(report_id)
            types, group_cache = self.group_types(report_id), {}
            source = []
            for raw, row in zip(raw_rows, self.materialize(report_id, raw_rows)):
                memberships = {}
                for definition in types:
                    group = self._group_for(str(definition["id"]), raw, group_cache)
                    if group:
                        memberships[str(definition["id"])] = str(group["id"])
                source.append({report_id: {"raw": raw, "row": row, "groups": memberships}})
            sources[report_id] = source
        combined, used, details = sources[report_ids[0]], {report_ids[0]}, []
        for edge in plan:
            left_side = "left" if edge["left_report"] in used else "right"
            right_side = "right" if left_side == "left" else "left"
            left_report, right_report = edge[f"{left_side}_report"], edge[f"{right_side}_report"]
            if right_report in used:
                continue
            left_field, right_field = edge[f"{left_side}_field"], edge[f"{right_side}_field"]
            def key_for(parts, report_id, field):
                part = parts.get(report_id)
                return match_key(part["raw"].get(field["key"]), field["type"]) if part else None
            pairs, counts = full_outer(
                combined, sources[right_report],
                lambda parts: key_for(parts, left_report, left_field),
                lambda parts: key_for(parts, right_report, right_field),
                left_field["label"], right_field["label"],
            )
            combined = [{**(left or {}), **(right or {})} for left, right in pairs]
            used.add(right_report)
            details.append({"rule_id": edge["id"], **counts})
        if identity:
            def identity_key(parts):
                part = parts.get(identity[0])
                return match_key(part["raw"].get(identity[1]["key"]), identity[1]["type"]) if part else None
            unique_index(combined, identity_key, identity[1]["label"])
        rows = []
        selected = {str(value) for value in group_ids}
        for parts in combined:
            memberships = {key: value for part in parts.values() for key, value in part["groups"].items()}
            if selected and not selected.intersection(memberships.values()):
                continue
            projected, invalid = {}, []
            for report_id, field in resolved:
                part = parts.get(report_id)
                projected[field["id"]] = part["row"].get(field["key"]) if part else (0 if field["type"] in {"number", "percent"} and field.get("kind") != "table" else None)
                if part and field["key"] in part["row"].get("__invalid_fields", []):
                    invalid.append(field["id"])
            projected["__group_ids"] = memberships
            if invalid:
                projected["__invalid_fields"] = invalid
            aliases = []
            for edge in plan:
                for side in ("left", "right"):
                    report_id, field = edge[f"{side}_report"], edge[f"{side}_field"]
                    part = parts.get(report_id)
                    key = match_key(part["raw"].get(field["key"]), field["type"]) if part else None
                    if key:
                        # Both aliases identify a confirmed match even if one side is
                        # absent in this period. Never manufacture a source value.
                        for endpoint in ("left_field_id", "right_field_id"):
                            aliases.append(public_row_key(edge[endpoint], key))
            if identity:
                key = public_row_key(identity_id, identity_key(parts))
                if key:
                    aliases.insert(0, key)
            aliases = list(dict.fromkeys(aliases))
            if aliases:
                projected["__row_key"], projected["__row_keys"] = aliases[0], aliases
            rows.append(projected)
        return {"fields": [self._public_field(field) for _, field in resolved], "rows": rows,
                **({"matching": {"rule_ids": [edge["id"] for edge in plan], "details": details}} if plan else {})}

    def validate_scope(self, field_ids, group_ids):
        """Check membership lineage without retrieving a snapshot or contacting a source."""
        report_ids = {report_id for report_id, _ in self._resolve_ids(field_ids)}
        if not isinstance(group_ids, list):
            raise ValidationError("Group scope must be a list of Groups.")
        for group_id in group_ids:
            group = self.groups.get(group_id)
            definition = self.groups.get_type(group["type_id"])
            if str(definition.get("report_id") or "") not in report_ids:
                raise ValidationError("The selected Group does not match these Fields.")

    def rank(self, field_ids, rows):
        """Resolve table-generated values after consumer filtering and ranking."""
        definitions = [field for _, field in self._resolve_ids(field_ids) if field.get("kind") == "table"]
        result = [dict(row) for row in rows]
        for field in definitions:
            type_id = str(field.get("group_type_id") or "")
            for index, row in enumerate(result):
                row[field["id"]] = index + 1
                if index or not type_id:
                    continue
                group_id = (row.get("__group_ids") or {}).get(type_id)
                if group_id:
                    theme = self.themes.effective_group_theme(group_id)
                    asset = (theme.get("assets") or {}).get(field.get("first_place_asset") or "medallion")
                    if asset:
                        row.setdefault("__field_assets", {})[field["id"]] = str(asset)
        return result

    @staticmethod
    def _decimals(value, default):
        if isinstance(value, bool):
            return default
        try:
            return min(max(int(value), 0), 8)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _default_decimals(cls, field_type):
        return 1 if field_type == "percent" else 2 if field_type == "number" else 0

    @staticmethod
    def _label(value):
        label = str(value or "").strip()[:120]
        if not label:
            raise ValidationError("Field name is required.")
        return label

    def _report_fields(self, report_id):
        return [
            {**dict(field), "kind": "report"}
            for field in self.reports.fields(report_id)
        ]

    def _custom_fields(self, report_id):
        result = []
        for raw in self.repos.fields.list(report_id):
            item = dict(raw)
            kind = str(item.get("kind") or "")
            if kind not in {"calculated", "group", "table"}:
                continue
            if kind == "table" and str(item.get("key") or "") != self.RANK_KEY:
                continue
            result.append(item)
        return result

    def _rank_field(self, report_id):
        stored = next(
            (
                item for item in self._custom_fields(report_id)
                if item.get("kind") == "table" and item.get("key") == self.RANK_KEY
            ),
            {},
        )
        return {
            "key": self.RANK_KEY,
            "label": str(stored.get("label") or "Rank"),
            "type": "number",
            "decimals": 0,
            "kind": "table",
            "group_type_id": str(stored.get("group_type_id") or ""),
            "first_place_asset": str(stored.get("first_place_asset") or "medallion"),
            "customized": bool(stored),
        }

    def fields(self, report_id):
        self.reports.get(report_id)
        custom = [item for item in self._custom_fields(report_id) if item.get("kind") != "table"]
        custom.sort(key=lambda item: (str(item.get("kind")), str(item.get("label")).casefold()))
        return [
            {**field, "id": self.field_id(report_id, field["key"]),
             **({"percent_input_scale": field.get("percent_input_scale", "auto")} if field.get("type") == "percent" else {})}
            for field in self._report_fields(report_id) + custom + [self._rank_field(report_id)]
        ]

    def field(self, report_id, field_key):
        key = str(field_key or "")
        item = next((field for field in self.fields(report_id) if str(field.get("key")) == key), None)
        if not item:
            raise ValidationError("Field not found.")
        return item

    def group_types(self, report_id):
        return [
            item for item in self.groups.list_types()
            if str(item.get("report_id") or "") == str(report_id)
        ]

    def catalog(self, report_id, sample_limit=8):
        report = self.reports.get(report_id)
        fields = self.fields(report_id)
        rows = self.materialize(report_id, self.reports.rows(report_id))
        rows = self.apply_rank(report_id, rows)
        return {
            "report": {"id": report_id, "name": str(report.get("name") or report_id)},
            "fields": fields,
            "sample_rows": rows[: max(1, min(int(sample_limit or 8), 20))],
            "group_types": self.group_types(report_id),
            "group_properties": [
                {"key": "group_name", "label": "Group Name", "type": "text"},
                {"key": "group_leader", "label": "Group Lead / Manager", "type": "text"},
                *[
                    {"key": f"asset:{key}", "label": value["label"], "type": "asset"}
                    for key, value in ASSETS.items()
                ],
            ],
        }

    def update_report_field(self, report_id, field_key, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        source = next(
            (item for item in self._report_fields(report_id) if str(item.get("key")) == str(field_key)),
            None,
        )
        if not source:
            raise ValidationError("Report Field not found.")
        if incoming.get("type") and incoming["type"] != source.get("type"):
            matching = self.matching_field_references(self.field_id(report_id, field_key))
            if matching:
                raise ValidationError(f"This Field is used by {matching[0]}. Remove that match before changing its display type.")
        return {
            **self.reports.update_report_field(report_id, {
                "field": field_key,
                "label": incoming.get("label"),
                "type": incoming.get("type"),
                "decimals": incoming.get("decimals"),
                **({"percent_input_scale": incoming["percent_input_scale"]} if "percent_input_scale" in incoming else {}),
            }),
            "kind": "report",
        }

    def _field_name_lookup(self, report_id):
        lookup = {}
        ambiguous = set()
        for field in self._report_fields(report_id):
            key = str(field.get("key") or "")
            for name in {key, str(field.get("label") or ""), str(field.get("source_label") or "")}:
                normalized = name.strip().casefold()
                if not normalized:
                    continue
                if normalized in lookup and lookup[normalized] != key:
                    ambiguous.add(normalized)
                else:
                    lookup[normalized] = key
        for name in ambiguous:
            lookup.pop(name, None)
        return lookup

    @staticmethod
    def _validate_formula_tree(tree):
        for node in ast.walk(tree):
            if isinstance(node, (ast.Expression, ast.Load, ast.Constant, ast.Name)):
                continue
            if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
                continue
            if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
                continue
            if isinstance(node, tuple(_BINARY_OPERATORS) + tuple(_UNARY_OPERATORS)):
                continue
            raise ValidationError("Use Report fields, numbers, text, parentheses, +, −, × or ÷ only.")

    def _compile_formula(self, report_id, formula):
        formula = str(formula or "").strip()
        if not formula:
            raise ValidationError("Formula is required.")
        lookup = self._field_name_lookup(report_id)
        references, variables = {}, {}

        def replace(match):
            requested = str(match.group(1) or "").strip()
            key = lookup.get(requested.casefold())
            if not key:
                raise ValidationError(f"Report Field '{requested}' was not found or has an ambiguous name.")
            variable = variables.setdefault(key, f"field_{len(variables)}")
            references[variable] = key
            return variable

        normalized = formula.replace("×", "*").replace("÷", "/").replace("−", "-")
        try:
            expression = _FIELD_TOKEN.sub(replace, normalized)
            tree = ast.parse(expression, mode="eval")
        except ValidationError:
            raise
        except (SyntaxError, ValueError) as exc:
            raise ValidationError("Formula is not valid.") from exc
        if not references:
            raise ValidationError("Choose at least one Report Field in the formula.")
        self._validate_formula_tree(tree)
        return expression, references

    def _calculated_definition(self, report_id, incoming, field_key=""):
        self.reports.get(report_id)
        incoming = incoming if isinstance(incoming, dict) else {}
        key = str(field_key or "").strip() or f"calculated-{uuid.uuid4().hex[:12]}"
        existing = self.repos.fields.get(report_id, key)
        if existing and existing.get("kind") != "calculated":
            raise ValidationError("Calculated Field not found.")
        field_type = str(incoming.get("type") or (existing or {}).get("type") or "number").lower()
        if field_type not in _CALCULATED_TYPES:
            raise ValidationError("Calculated Fields can display as Number, Text, or Percentage.")
        formula = str(incoming.get("formula") or (existing or {}).get("formula") or "").strip()
        expression, references = self._compile_formula(report_id, formula)
        definition = {
            "key": key,
            "kind": "calculated",
            "label": self._label(incoming.get("label") or (existing or {}).get("label")),
            "type": field_type,
            "decimals": 0 if field_type == "text" else self._decimals(
                incoming.get("decimals"), self._default_decimals(field_type)
            ),
            "formula": formula,
            "expression": expression,
            "references": references,
        }
        if field_type == "percent":
            definition["percent_input_scale"] = self.reports.normalize_percent_input_scale(
                incoming.get("percent_input_scale", (existing or {}).get("percent_input_scale"))
            )
        return definition

    def preview_calculated(self, report_id, incoming):
        """Evaluate a draft through the same compiler/materializer as saved Fields.

        Cached Report rows only: no persistence, refresh, or invented samples.
        Report identity and formula references remain inside the Fields owner.
        """
        definition = self._calculated_definition(report_id, incoming, "__draft_calculation")
        definitions = [*self.fields(report_id), definition]
        rows = self.materialize(report_id, self.reports.rows(report_id), definitions=definitions)
        keys = set(definition["references"].values())
        visible = [field for field in definitions if field["key"] in keys or field is definition]
        return {"kind": "table", "name": "Each row · cached Report data", "fields": visible,
                "rows": rows, "total_rows": len(rows), "field": definition,
                "unavailable_rows": sum(definition["key"] in row.get("__invalid_fields", []) for row in rows)}

    def save_calculated(self, report_id, incoming, field_key=""):
        definition = self._calculated_definition(report_id, incoming, field_key)
        self.repos.fields.save(report_id, definition)
        self.repos.meta.bump("settings_version")
        return definition

    def save_group(self, report_id, incoming, field_key=""):
        self.reports.get(report_id)
        incoming = incoming if isinstance(incoming, dict) else {}
        key = str(field_key or "").strip() or f"group-field-{uuid.uuid4().hex[:12]}"
        existing = self.repos.fields.get(report_id, key)
        if existing and existing.get("kind") != "group":
            raise ValidationError("Group Field not found.")
        type_id = str(incoming.get("group_type_id") or (existing or {}).get("group_type_id") or "").strip()
        definition = self.groups.get_type(type_id)
        if str(definition.get("report_id") or "") != str(report_id):
            raise ValidationError("Choose a Group Type supplied by this Report.")
        property_key = str(incoming.get("property") or (existing or {}).get("property") or "").strip()
        valid = {"group_name", "group_leader", *[f"asset:{key}" for key in ASSETS]}
        if property_key not in valid:
            raise ValidationError("Choose a valid Group property or asset.")
        definition = {
            "key": key,
            "kind": "group",
            "label": self._label(incoming.get("label") or (existing or {}).get("label")),
            "type": "asset" if property_key.startswith("asset:") else "text",
            "decimals": 0,
            "group_type_id": type_id,
            "property": property_key,
        }
        self.repos.fields.save(report_id, definition)
        self.repos.meta.bump("settings_version")
        return definition

    def save_rank(self, report_id, incoming):
        self.reports.get(report_id)
        incoming = incoming if isinstance(incoming, dict) else {}
        type_id = str(incoming.get("group_type_id") or "").strip()
        if type_id:
            definition = self.groups.get_type(type_id)
            if str(definition.get("report_id") or "") != str(report_id):
                raise ValidationError("Choose a Group Type supplied by this Report.")
        asset = str(incoming.get("first_place_asset") or "medallion").strip()
        if asset not in ASSETS:
            raise ValidationError("Choose a valid first-place asset.")
        field = {
            "key": self.RANK_KEY,
            "kind": "table",
            "label": self._label(incoming.get("label") or "Rank"),
            "type": "number",
            "decimals": 0,
            "group_type_id": type_id,
            "first_place_asset": asset,
            "customized": True,
        }
        self.repos.fields.save(report_id, field)
        self.repos.meta.bump("settings_version")
        return field

    def save(self, report_id, incoming, field_key=""):
        incoming = incoming if isinstance(incoming, dict) else {}
        kind = str(incoming.get("kind") or "").strip().lower()
        if field_key:
            existing = self.field(report_id, field_key)
            kind = str(existing.get("kind") or kind)
        if kind == "report":
            return self.update_report_field(report_id, field_key or incoming.get("key"), incoming)
        if kind == "calculated":
            return self.save_calculated(report_id, incoming, field_key)
        if kind == "group":
            return self.save_group(report_id, incoming, field_key)
        if kind == "table" and (not field_key or str(field_key) == self.RANK_KEY):
            return self.save_rank(report_id, incoming)
        raise ValidationError("Choose Calculated Field, Group Field, or Table Field.")

    def delete(self, report_id, field_key):
        field = self.field(report_id, field_key)
        if field.get("kind") not in {"calculated", "group"}:
            raise ValidationError("Report and Table Fields cannot be deleted.")
        used_by = [*(self.dependencies(field["id"]) if self.dependencies else []), *self.matching_field_references(field["id"])]
        if used_by:
            raise ValidationError(f"This Field is used by {used_by[0]}. Remove or replace it there first.")
        for screen in self.repos.screens.list():
            for table in screen.get("tables") or []:
                table_report_id = str(table.get("report_id") or "")
                group_id = str(table.get("group_id") or "")
                if group_id:
                    try:
                        table_report_id = str(self.groups.get(group_id).get("report_id") or "")
                    except ValidationError:
                        table_report_id = ""
                if (
                    table_report_id == str(report_id)
                    and field_key in [str(value) for value in table.get("columns") or []]
                ):
                    raise ValidationError("This Field is used by a Screen. Remove it from that Screen first.")
        for preset in self.repos.table_presets.list():
            if str(preset.get("report_id") or "") != str(report_id):
                continue
            if (
                field_key in [str(value) for value in preset.get("columns") or []]
                or str(preset.get("sort_field") or "") == str(field_key)
            ):
                raise ValidationError("This Field is used by a Table Preset. Change that Preset first.")
        if not self.repos.fields.delete(report_id, field_key):
            raise ValidationError("Field not found.")
        self.repos.meta.bump("settings_version")
        return field

    @staticmethod
    def _formula_value(value):
        if value is None or value == "":
            return 0.0
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip()
        numeric = text.replace(",", "").replace("$", "")
        if numeric.endswith("%"):
            try:
                return float(numeric[:-1]) / 100
            except ValueError:
                return text
        try:
            return float(numeric)
        except ValueError:
            return text

    @classmethod
    def _eval_node(cls, node, values):
        if isinstance(node, ast.Expression):
            return cls._eval_node(node.body, values)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return values.get(node.id, 0.0)
        if isinstance(node, ast.UnaryOp):
            return _UNARY_OPERATORS[type(node.op)](cls._eval_node(node.operand, values))
        if isinstance(node, ast.BinOp):
            left, right = cls._eval_node(node.left, values), cls._eval_node(node.right, values)
            if isinstance(node.op, ast.Add) and (isinstance(left, str) or isinstance(right, str)):
                return f"{left}{right}"
            return _BINARY_OPERATORS[type(node.op)](left, right)
        raise ValueError("Unsupported formula node")

    @classmethod
    def _calculate(cls, definition, row):
        values = {
            variable: cls._formula_value(row.get(field_key))
            for variable, field_key in (definition.get("references") or {}).items()
        }
        try:
            tree = ast.parse(str(definition.get("expression") or ""), mode="eval")
            cls._validate_formula_tree(tree)
            value = cls._eval_node(tree, values)
            if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
                return None
            return value
        except (ArithmeticError, TypeError, ValueError):
            return None

    def _group_for(self, type_id, row, cache):
        definition = self.groups.get_type(type_id)
        member_key = str(definition.get("member_key_field") or "")
        lookup = str((row or {}).get(member_key) or "").strip().casefold()
        if not lookup:
            return None
        if type_id not in cache:
            mapping = {}
            for group in self.groups.list(type_id):
                for value in group.get("member_keys") or []:
                    mapping[str(value or "").strip().casefold()] = group
            cache[type_id] = mapping
        return cache[type_id].get(lookup)

    def materialize(self, report_id, rows, *, definitions=None):
        definitions = self.fields(report_id) if definitions is None else definitions
        custom = [field for field in definitions if field.get("kind") in {"calculated", "group"}]
        numeric = [field for field in definitions if field.get("kind") == "report" and field.get("type") in {"number", "percent"}]
        group_cache, theme_cache = {}, {}
        result = []
        for raw in rows or []:
            row = dict(raw)
            invalid = set()
            for field in numeric:
                key, value = field["key"], row.get(field["key"])
                if value is None or isinstance(value, str) and not value.strip():
                    row[key] = 0
                elif numeric_value(value) is None:
                    row[key] = None
                    invalid.add(key)
            for field in custom:
                key = str(field.get("key") or "")
                if field.get("kind") == "calculated":
                    row[key] = None if invalid.intersection((field.get("references") or {}).values()) else self._calculate(field, row)
                    if field.get("type") in {"number", "percent"} and (row[key] is None or numeric_value(row[key]) is None):
                        row[key] = None
                        invalid.add(key)
                    continue
                group = self._group_for(str(field.get("group_type_id") or ""), row, group_cache)
                property_key = str(field.get("property") or "")
                if not group:
                    row[key] = ""
                elif property_key == "group_name":
                    row[key] = str(group.get("name") or "")
                elif property_key == "group_leader":
                    row[key] = str(group.get("leader_member_key") or "")
                elif property_key.startswith("asset:"):
                    group_id = str(group.get("id") or "")
                    if group_id not in theme_cache:
                        theme_cache[group_id] = self.themes.effective_group_theme(group_id)
                    row[key] = str((theme_cache[group_id].get("assets") or {}).get(property_key[6:]) or "")
            if invalid:
                row["__invalid_fields"] = sorted(invalid)
            result.append(row)
        return result

    def apply_rank(self, report_id, rows):
        rows = [dict(row) for row in rows or []]
        rank = self._rank_field(report_id)
        type_id = str(rank.get("group_type_id") or "")
        asset_key = str(rank.get("first_place_asset") or "medallion")
        group_cache = {}
        for index, row in enumerate(rows):
            row[self.RANK_KEY] = index + 1
            if index != 0 or not type_id:
                continue
            group = self._group_for(type_id, row, group_cache)
            if not group:
                continue
            theme = self.themes.effective_group_theme(group.get("id"))
            asset = str((theme.get("assets") or {}).get(asset_key) or "")
            if asset:
                row.setdefault("__field_assets", {})[self.RANK_KEY] = asset
        return rows
