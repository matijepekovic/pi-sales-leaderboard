"""Read-only Salesforce Flow v30 audit collector, isolated from resulting writes.

Run: python3 -m printer_app.mod_resulting.flow_audit --org work

Only approved Salesforce CLI READ operations are permitted. The separate
temporary Salesforce project receives downloaded metadata locally; neither
End of Day nor ResultingService/ResultingSalesforceAdapter.apply is invoked.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET

from .salesforce_adapter import (
    LEAD, LEAD_FIELDS, PR, PR_APPOINTMENT_DATE, PR_ISSUED_COUNT,
    PRODUCT_RESULT, REVIEW_FIELD, SA, SERVICE_APPOINTMENT, WO,
    WO_APPOINTMENT_DATE, WO_APPOINTMENT_DATETIME, WO_LEAD, WORK_ORDER,
)


class FlowAuditError(RuntimeError):
    pass


NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,254}\Z")
READ_COMMANDS = {
    ("org", "list", "metadata"),
    ("data", "query"),
    ("sobject", "describe"),
    ("project", "retrieve", "start"),
}
FLOW_ELEMENTS = {
    "actionCalls", "apexPluginCalls", "assignments", "collectionProcessors",
    "decisions", "formulas", "loops", "recordCreates", "recordDeletes",
    "recordLookups", "recordUpdates", "screens", "stages", "start", "subflows",
    "transforms", "variables", "waits",
}
FLOW_REFERENCES = {
    "assignToReference", "elementReference", "field",
    "fieldReference", "leftValueReference", "object",
    "outputReference", "targetReference", "inputReference",
}


def _tag(node):
    return node.tag.rsplit("}", 1)[-1]


def _children(node, name):
    return [child for child in node if _tag(child) == name]


def _first(node, name):
    for child in node:
        if _tag(child) == name:
            return child
    return None


def _text(node, name):
    child = _first(node, name)
    return (child.text or "").strip() if child is not None else ""


def _json_result(result, purpose):
    if not isinstance(result, dict) or result.get("status") not in (0, None):
        raise FlowAuditError("Salesforce did not return a successful " + purpose + ".")
    return result.get("result")


class ReadOnlySalesforceCLI:
    """Allowlist applies to every subprocess call, irrespective of live-write settings."""

    def __init__(self, *, executable="sf", org="work", runner=subprocess.run):
        if not org or org.startswith("-") or any(c.isspace() for c in org):
            raise FlowAuditError("Invalid Salesforce org alias.")
        self.executable = executable
        self.org = org
        self.runner = runner

    def call(self, args, *, cwd=None, timeout=180):
        if not any(tuple(args[:len(prefix)]) == prefix for prefix in READ_COMMANDS):
            raise FlowAuditError("Forbidden Salesforce CLI operation in read-only audit.")
        command = [
            self.executable, *args, "--target-org", self.org, "--json",
        ]
        try:
            completed = self.runner(
                command, cwd=cwd, capture_output=True, text=True,
                check=False, timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FlowAuditError(
                "Salesforce CLI read failed or timed out: " + " ".join(args[:3])
            ) from exc
        try:
            payload = json.loads(completed.stdout)
        except (ValueError, TypeError) as exc:
            raise FlowAuditError(
                "Salesforce CLI produced no usable JSON for " + " ".join(args[:3])
                + "; check authentication and metadata permissions."
            ) from exc
        if completed.returncode or payload.get("status") not in (0, None):
            raise FlowAuditError(
                "Salesforce rejected read-only " + " ".join(args[:3])
                + "; check the org alias and metadata permissions."
            )
        return payload.get("result")

    def list_flows(self):
        rows = self.call(["org", "list", "metadata", "--metadata-type", "Flow"])
        if isinstance(rows, dict):
            rows = rows.get("files", rows.get("items", []))
        if not isinstance(rows, list):
            raise FlowAuditError("Salesforce Flow metadata list is incomplete.")
        return [
            {"fullName": str(item.get("fullName", "")).strip(),
             "fileName": str(item.get("fileName", "")).strip()}
            for item in rows if isinstance(item, dict)
        ]

    def query(self, soql):
        rows = self.call(["data", "query", "--query", soql])
        if not isinstance(rows, dict) or not isinstance(rows.get("records"), list):
            raise FlowAuditError("Salesforce returned an invalid read-only query.")
        if rows.get("done") is False:
            raise FlowAuditError("Salesforce query is incomplete.")
        return rows["records"]

    def describe(self, name):
        result = self.call(["sobject", "describe", "--sobject", name])
        if not isinstance(result, dict) or result.get("name") != name:
            raise FlowAuditError("Salesforce object describe is invalid: " + name)
        if not isinstance(result.get("fields"), list):
            raise FlowAuditError("Salesforce field list is incomplete: " + name)
        return result

    def retrieve_flow(self, api_name, version, project):
        if not NAME.fullmatch(api_name) or not 1 <= version <= 9999:
            raise FlowAuditError("Invalid Flow API name or version.")
        # Explicit -30 ensures this audit does NOT silently use latest Flow.
        retrieval = project / "retrieved"
        self.call(
            ["project", "retrieve", "start", "--metadata",
             "Flow:" + api_name + "-" + str(version),
             "--output-dir", str(retrieval), "--wait", "6"],
            cwd=project, timeout=420,
        )
        matches = list(retrieval.rglob("*.flow-meta.xml"))
        expected = {api_name + ".flow-meta.xml",
                    api_name + "-" + str(version) + ".flow-meta.xml"}
        matches = [path for path in matches if path.name in expected]
        if len(matches) != 1:
            raise FlowAuditError(
                "Flow version " + str(version) + " was not uniquely retrieved. "
                "No substitute/latest Flow will be used."
            )
        return matches[0]


def select_flow(flows, definitions, explicit_name=""):
    all_names = {
        name for row in flows if (name := row.get("fullName", ""))
        and NAME.fullmatch(name)
    }
    names = set(all_names)
    for row in definitions:
        name = str(row.get("ApiName") or "")
        if NAME.fullmatch(name):
            names.add(name)
    if explicit_name:
        if not NAME.fullmatch(explicit_name):
            raise FlowAuditError("Invalid explicit Flow API name.")
        if explicit_name not in names:
            raise FlowAuditError(
                "Requested Flow not found; possible matches: "
                + ", ".join(sorted(names)[:30])
            )
        return explicit_name
    candidates = set()
    for name in names:
        if "result" in name.lower() and "appoint" in name.lower():
            candidates.add(name)
    for row in definitions:
        label = str(row.get("Label") or "")
        name = str(row.get("ApiName") or "")
        if "result" in label.lower() and "appoint" in label.lower() and name in names:
            candidates.add(name)
    if len(candidates) == 1:
        return next(iter(candidates))
    # Do not substitute an arbitrary Flow if name discovery is ambiguous.
    if not candidates:
        raise FlowAuditError(
            "Result Appointment Flow was not found. Available Flow names: "
            + ", ".join(sorted(names)[:40])
            + ". Supply --flow-name with the exact API name."
        )
    raise FlowAuditError(
        "Multiple Result Appointment flows found: "
        + ", ".join(sorted(candidates))
        + ". Supply --flow-name with the exact API name."
    )


def field_requirements():
    """Use the actual adapter's API mappings, never a parallel field map."""
    return {
        WORK_ORDER: set(WO.values()) | {
            WO_LEAD, WO_APPOINTMENT_DATE, WO_APPOINTMENT_DATETIME, REVIEW_FIELD,
        },
        LEAD: set(LEAD_FIELDS.values()) | {"Appointment_Date__c"},
        SERVICE_APPOINTMENT: set(SA.values()),
        PRODUCT_RESULT: set(PR.values()) | {
            PR_APPOINTMENT_DATE, PR_ISSUED_COUNT,
        },
    }


def relevant_fields(schema, required):
    rows = {field.get("name"): field for field in schema["fields"]
            if isinstance(field, dict) and isinstance(field.get("name"), str)}
    selected = {}
    for name in sorted(required):
        source = rows.get(name)
        if source is None:
            selected[name] = {"present": False}
            continue
        selected[name] = {
            "present": True,
            "type": source.get("type"),
            "updateable": source.get("updateable") is True,
            "createable": source.get("createable") is True,
            "referenceTo": source.get("referenceTo") or [],
            "picklistValues": [
                option.get("value") for option in source.get("picklistValues", [])
                if isinstance(option, dict) and option.get("active") is True
            ],
        }
    return selected


def flow_inventory(contents):
    if len(contents) > 16_000_000:
        raise FlowAuditError("Flow XML is too large to parse safely.")
    if b"<!DOCTYPE" in contents.upper() or b"<!ENTITY" in contents.upper():
        raise FlowAuditError("Flow metadata must not contain DTD or entities.")
    try:
        root = ET.fromstring(contents)
    except ET.ParseError as exc:
        raise FlowAuditError("Retrieved Salesforce Flow XML is invalid.") from exc
    if _tag(root) != "Flow":
        raise FlowAuditError("Retrieved metadata is not a Salesforce Flow.")

    elements = []
    for node in root:
        kind = _tag(node)
        if kind not in FLOW_ELEMENTS:
            continue
        references = sorted({
            (child.text or "").strip()
            for child in node.iter()
            if _tag(child) in FLOW_REFERENCES and (child.text or "").strip()
        })
        connectors = sorted({
            (child.text or "").strip()
            for child in node.iter()
            if _tag(child) == "targetReference" and (child.text or "").strip()
        })
        entry = {
            "type": kind, "name": _text(node, "name"),
            "label": _text(node, "label"),
            "object": _text(node, "object"),
            "references": references,
            "connectors": connectors,
        }
        if kind == "decisions":
            entry["rules"] = []
            for rule in _children(node, "rules"):
                entry["rules"].append({
                    "name": _text(rule, "name"),
                    "conditionLogic": _text(rule, "conditionLogic"),
                    "conditions": [
                        {"left": _text(cond, "leftValueReference"),
                         "operator": _text(cond, "operator"),
                         "right": ET.tostring(_first(cond, "rightValue"),
                                             encoding="unicode")
                           if _first(cond, "rightValue") is not None else ""}
                        for cond in _children(rule, "conditions")
                    ],
                })
        if kind in ("recordCreates", "recordUpdates", "recordDeletes"):
            entry["assigned_fields"] = sorted({
                _text(field, "field")
                for field in _children(node, "inputAssignments")
                if _text(field, "field")
            })
        elements.append(entry)
    return {
        "flow_status": _text(root, "status"),
        "process_type": _text(root, "processType"),
        "api_version": _text(root, "apiVersion"),
        "elements": elements,
        "element_counts": {
            kind: sum(item["type"] == kind for item in elements)
            for kind in sorted({item["type"] for item in elements})
        },
    }


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    path.chmod(0o600)


def collect(*, org="work", flow_name="", version=30, output=None,
            executable="sf", runner=subprocess.run):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(output).expanduser().resolve() if output else (
        Path.home() / ("stats-flow30-audit-" + stamp)
    )
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    project = folder / "_temporary_salesforce_project"
    project.mkdir(mode=0o700)
    (project / "sfdx-project.json").write_text(
        json.dumps({"packageDirectories": [{"path":"force-app","default":True}],
                    "namespace": "", "name": "stats-flow30-read-only-audit"}),
        encoding="utf-8",
    )
    cli = ReadOnlySalesforceCLI(executable=executable, org=org, runner=runner)

    warnings = []
    definitions = []
    try:
        definitions = cli.query(
            "SELECT Id, ApiName, Label, ActiveVersionId, LatestVersionId, "
            "VersionNumber FROM FlowDefinitionView WHERE ApiName LIKE '%Result%'"
        )
    except FlowAuditError:
        warnings.append(
            "FlowDefinitionView read unavailable; version activation "
            "must be verified separately."
        )
    flows = cli.list_flows()
    name = select_flow(flows, definitions, flow_name)
    _write_json(folder / "flow_identity.json", {
        "selected_api_name": name, "requested_flow_version": version,
        "definition": [
            {key: row.get(key) for key in (
                "ApiName", "Label", "ActiveVersionId", "LatestVersionId",
                "VersionNumber",
            )}
            for row in definitions if row.get("ApiName") == name
        ],
    })
    retrieved_path = cli.retrieve_flow(name, version, project)
    data = retrieved_path.read_bytes()
    inventory = flow_inventory(data)
    flow_file = folder / ("flow_version_" + str(version) + ".xml")
    flow_file.write_bytes(data)
    flow_file.chmod(0o600)
    _write_json(folder / "flow_inventory.json", inventory)

    # Metadata reads only; no customer records, and no data DML.
    schemas = {}
    for object_name, field_names in field_requirements().items():
        schemas[object_name] = relevant_fields(
            cli.describe(object_name), field_names,
        )
    _write_json(folder / "stats_field_metadata.json", schemas)
    issued = schemas[PRODUCT_RESULT].get(PR_ISSUED_COUNT, {})
    appointment = schemas[PRODUCT_RESULT].get(PR_APPOINTMENT_DATE, {})
    checks = {
        PR_ISSUED_COUNT: {
            "exists": issued.get("present", False),
            "boolean": issued.get("type") == "boolean",
            "writable": issued.get("updateable") is True
                        and issued.get("createable") is True,
        },
        PR_APPOINTMENT_DATE: {
            "exists": appointment.get("present", False),
            "date": appointment.get("type") == "date",
            "writable": appointment.get("updateable") is True
                        and appointment.get("createable") is True,
        },
    }
    report = {
        "mode": "read_only",
        "salesforce_records_read": 0,
        "salesforce_records_modified": 0,
        "flow_api_name": name,
        "flow_version_requested": version,
        "flow_version_confirmation": "version_specific_metadata_selector",
        "flow_status_in_xml": inventory["flow_status"],
        "flow_element_counts": inventory["element_counts"],
        "phase3_critical_fields": checks,
        "warnings": warnings,
        "parity_verified": False,
        "parity_note": "Flow XML and live field metadata were collected. "
                       "A field-by-field parity review is still required. "
                       "No Flow was executed.",
    }
    _write_json(folder / "summary.json", report)
    bundle = folder / "flow_v30_readonly_bundle.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in (
            flow_file, folder / "flow_identity.json",
            folder / "flow_inventory.json",
            folder / "stats_field_metadata.json", folder / "summary.json",
        ):
            archive.write(path, arcname=path.name)
    bundle.chmod(0o600)
    # Avoid leaving a second copy of retrieved metadata in the temporary
    # project (which can be large); keep just the output archive and reports.
    import shutil
    shutil.rmtree(project)
    return report, bundle


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only Salesforce Flow v30 and Stats field audit.")
    parser.add_argument("--org", default="work")
    parser.add_argument("--flow-name", default="",
                        help="Exact API name if multiple flows match.")
    parser.add_argument("--version", type=int, default=30)
    parser.add_argument("--output", help="New private output directory.")
    parser.add_argument("--sf", default="sf", help="Salesforce CLI executable.")
    args = parser.parse_args(argv)
    try:
        summary, path = collect(
            org=args.org, flow_name=args.flow_name,
            version=args.version, output=args.output,
            executable=args.sf,
        )
    except FlowAuditError as exc:
        print("Flow audit failed (no Salesforce writes): " + str(exc),
              file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    print("READ-ONLY AUDIT BUNDLE: " + str(path))
    print("Share the ZIP privately for exact Flow v30 vs Stats comparison.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
