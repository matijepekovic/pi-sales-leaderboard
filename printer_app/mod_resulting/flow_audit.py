"""Read-only inspection of an exact Salesforce Result Appointment Flow version.

This standalone adapter never calls MOD Resulting submission, deploys metadata,
or changes Salesforce records. Salesforce Tooling API Flow records identify
historical versions by record ID; the Metadata API's Flow:<name>-30 selector
is not valid for modern Salesforce Flow retrieval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from .salesforce_adapter import (
    LEAD, LEAD_FIELDS, PR, PR_APPOINTMENT_DATE, PR_ISSUED_COUNT,
    PRODUCT_RESULT, REVIEW_FIELD, SA, SERVICE_APPOINTMENT, WO,
    WO_APPOINTMENT_DATE, WO_APPOINTMENT_DATETIME, WO_LEAD, WORK_ORDER,
)


class FlowAuditError(RuntimeError):
    pass


NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,254}\Z")
ID = re.compile(r"[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?\Z")
READ_COMMANDS = {("data", "query"), ("sobject", "describe")}
FLOW_ELEMENTS = {
    "actionCalls", "apexPluginCalls", "assignments", "collectionProcessors",
    "decisions", "formulas", "loops", "recordCreates", "recordDeletes",
    "recordLookups", "recordUpdates", "screens", "stages", "start",
    "subflows", "transforms", "variables", "waits",
}
FLOW_REFERENCES = {
    "assignToReference", "elementReference", "field", "fieldReference",
    "leftValueReference", "object", "outputReference", "targetReference",
    "inputReference",
}


def _safe_error(data):
    """Return a useful Salesforce failure without copying credentials or JSON."""
    if not isinstance(data, dict):
        return "Salesforce returned an unexpected error."
    parts = []
    name = data.get("name") or data.get("errorCode") or data.get("error")
    if isinstance(name, str) and len(name) < 120:
        parts.append(name)
    message = data.get("message")
    if not isinstance(message, str):
        detail = data.get("result")
        if isinstance(detail, dict):
            message = detail.get("message")
    if isinstance(message, str):
        message = re.sub(
            r"(?i)(access_token|refresh_token|authorization|password)\s*[:=]\s*\S+",
            r"\1=[REDACTED]", message,
        )
        message = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", message)
        parts.append(message[:400])
    return ": ".join(parts) or "Salesforce did not report a reason."


class ReadOnlySalesforceCLI:
    """Every executed process is checked against an explicit read-only allowlist."""

    def __init__(self, *, executable="sf", org="work", runner=subprocess.run):
        if not org or org.startswith("-") or any(c.isspace() for c in org):
            raise FlowAuditError("Invalid Salesforce org alias.")
        self.executable = executable
        self.org = org
        self.runner = runner

    def call(self, args, *, timeout=75):
        if tuple(args[:2]) not in READ_COMMANDS:
            raise FlowAuditError("Forbidden Salesforce CLI operation in read-only audit.")
        command = [
            self.executable, *args, "--target-org", self.org, "--json",
        ]
        try:
            completed = self.runner(
                command, capture_output=True, text=True,
                check=False, timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FlowAuditError(
                "Salesforce CLI read failed or timed out: " + " ".join(args[:2])
            ) from exc
        try:
            response = json.loads(completed.stdout)
        except (TypeError, ValueError) as exc:
            raise FlowAuditError(
                "Salesforce CLI returned invalid JSON for " + " ".join(args[:2])
                + ". Confirm the 'work' alias is authenticated."
            ) from exc
        if (not isinstance(response, dict) or completed.returncode
                or response.get("status") not in (0, None)):
            raise FlowAuditError(
                "Salesforce read-only " + " ".join(args[:2]) + " failed: "
                + _safe_error(response)
            )
        return response.get("result")

    def query(self, soql, *, tooling=False):
        args = ["data", "query", "--query", soql]
        if tooling:
            args.append("--use-tooling-api")
        result = self.call(args)
        if not isinstance(result, dict) or not isinstance(result.get("records"), list):
            raise FlowAuditError("Salesforce returned an invalid query result.")
        if result.get("done") is False:
            raise FlowAuditError("Salesforce query is incomplete; no partial data accepted.")
        return result["records"]

    def flow_versions(self, version):
        if type(version) is not int or not 1 <= version <= 9999:
            raise FlowAuditError("Flow version must be a positive integer.")
        # Unlike Metadata API, the Tooling API stores each Flow version as a
        # separately addressable record. Query names/status only; no interviews.
        soql = (
            "SELECT Id, Definition.DeveloperName, MasterLabel, VersionNumber, Status "
            "FROM Flow WHERE VersionNumber = " + str(version) + " LIMIT 2000"
        )
        records = self.query(soql, tooling=True)
        if len(records) == 2000:
            raise FlowAuditError("Flow version query may be truncated.")
        return records

    def flow_metadata(self, record_id):
        if not isinstance(record_id, str) or not ID.fullmatch(record_id):
            raise FlowAuditError("Invalid Flow version identity.")
        # Metadata field requires a query restricted to one Flow ID.
        rows = self.query(
            "SELECT Id, Metadata FROM Flow WHERE Id = '" + record_id + "' LIMIT 1",
            tooling=True,
        )
        if len(rows) != 1 or rows[0].get("Id") != record_id:
            raise FlowAuditError("Exact Flow version metadata could not be retrieved.")
        value = rows[0].get("Metadata")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError as exc:
                raise FlowAuditError("Flow metadata is not valid JSON.") from exc
        if not isinstance(value, dict) or not value:
            raise FlowAuditError("Flow version metadata is unavailable.")
        return value

    def describe(self, name):
        result = self.call(["sobject", "describe", "--sobject", name])
        if not isinstance(result, dict) or result.get("name") != name:
            raise FlowAuditError("Salesforce object describe is invalid: " + name)
        if not isinstance(result.get("fields"), list):
            raise FlowAuditError("Salesforce field list is incomplete: " + name)
        return result


def select_flow(versions, version, explicit_name=""):
    """Return only a uniquely identified, exact-version Flow record."""
    matches = []
    for row in versions:
        if not isinstance(row, dict) or row.get("VersionNumber") != version:
            continue
        definition = row.get("Definition")
        name = (definition or {}).get("DeveloperName") if isinstance(definition, dict) else ""
        label = row.get("MasterLabel") or ""
        if not isinstance(name, str) or not NAME.fullmatch(name):
            continue
        if explicit_name:
            if name != explicit_name:
                continue
        elif not (
            ("result" in name.casefold() and "appoint" in name.casefold())
            or ("result" in str(label).casefold()
                and "appoint" in str(label).casefold())
        ):
            continue
        if not isinstance(row.get("Id"), str) or not ID.fullmatch(row["Id"]):
            raise FlowAuditError("Flow version has no valid record identity.")
        matches.append({"id": row["Id"], "name": name, "label": label,
                        "version": row["VersionNumber"], "status": row.get("Status")})
    if explicit_name and not NAME.fullmatch(explicit_name):
        raise FlowAuditError("Invalid Flow API name.")
    if len(matches) != 1:
        candidate_names = sorted({
            (row.get("Definition") or {}).get("DeveloperName", "")
            for row in versions if isinstance(row, dict)
            and isinstance(row.get("Definition"), dict)
            and row.get("VersionNumber") == version
        })
        raise FlowAuditError(
            "Expected one Result Appointment Flow version " + str(version)
            + "; found " + str(len(matches)) + ". "
            + ("Candidates: " + ", ".join(candidate_names[:30]) + ". "
               if candidate_names else "No accessible Flow versions. ")
            + "Use --flow-name with the exact API name if needed."
        )
    return matches[0]


def field_requirements():
    """Derive field names from the real adapter; no parallel API field mapping."""
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


def _references(value):
    found = set()

    def visit(node):
        if isinstance(node, dict):
            for key, item in node.items():
                if key in FLOW_REFERENCES and isinstance(item, str) and item:
                    found.add(item)
                visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(value)
    return sorted(found)


def flow_inventory(metadata):
    """Inventory only real Flow Tooling API metadata, never guessed steps."""
    if not isinstance(metadata, dict):
        raise FlowAuditError("Flow version metadata must be an object.")
    elements = []
    for kind in sorted(FLOW_ELEMENTS):
        raw = metadata.get(kind)
        if raw is None:
            continue
        nodes = raw if isinstance(raw, list) else [raw]
        for node in nodes:
            if not isinstance(node, dict):
                raise FlowAuditError("Flow metadata element has invalid structure.")
            element = {
                "type": kind,
                "name": node.get("name") or "",
                "label": node.get("label") or "",
                "object": node.get("object") or "",
                "references": _references(node),
            }
            if kind == "decisions":
                rules = node.get("rules") or []
                if not isinstance(rules, list):
                    rules = [rules]
                element["rules"] = [
                    {"name": rule.get("name"),
                     "conditionLogic": rule.get("conditionLogic"),
                     "conditions": rule.get("conditions") or []}
                    for rule in rules if isinstance(rule, dict)
                ]
            if kind in ("recordCreates", "recordUpdates", "recordDeletes"):
                entries = node.get("inputAssignments") or []
                if not isinstance(entries, list):
                    entries = [entries]
                element["assigned_fields"] = sorted({
                    entry["field"] for entry in entries
                    if isinstance(entry, dict) and isinstance(entry.get("field"), str)
                })
            elements.append(element)
    return {
        "flow_status": metadata.get("status"),
        "process_type": metadata.get("processType"),
        "api_version": metadata.get("apiVersion"),
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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = Path(output).expanduser().resolve() if output else (
        Path.home() / ("stats-flow30-audit-" + stamp)
    )
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    cli = ReadOnlySalesforceCLI(executable=executable, org=org, runner=runner)

    # The previous Metadata API list/Flow:name-30 retrieval was invalid for
    # modern Flow versions. Tooling API binds the selected version to its ID.
    identity = select_flow(cli.flow_versions(version), version, flow_name)
    metadata = cli.flow_metadata(identity["id"])
    inventory = flow_inventory(metadata)
    _write_json(folder / "flow_identity.json", identity)
    _write_json(folder / ("flow_version_" + str(version) + ".json"), metadata)
    _write_json(folder / "flow_inventory.json", inventory)

    schemas = {}
    for object_name, names in field_requirements().items():
        schemas[object_name] = relevant_fields(
            cli.describe(object_name), names,
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
        "salesforce_customer_records_read": 0,
        "salesforce_records_modified": 0,
        "flow_api_name": identity["name"],
        "flow_version_requested": version,
        "flow_version_confirmed": identity["version"] == version,
        "flow_version_record_id": identity["id"],
        "version_30_active": identity["status"] == "Active" if version == 30 else None,
        "version_status": identity["status"],
        "source": "Tooling_API_Flow_by_exact_version_id",
        "flow_element_counts": inventory["element_counts"],
        "phase3_critical_fields": checks,
        "parity_verified": False,
        "parity_note": "Metadata for an exact Flow version and live field "
                       "definitions were collected. Compare decisions and assignments "
                       "against Stats before claiming parity; no Flow was executed.",
    }
    _write_json(folder / "summary.json", report)
    bundle = folder / ("flow_v" + str(version) + "_readonly_bundle.zip")
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in (
            folder / "flow_identity.json",
            folder / ("flow_version_" + str(version) + ".json"),
            folder / "flow_inventory.json", folder / "stats_field_metadata.json",
            folder / "summary.json",
        ):
            archive.write(path, arcname=path.name)
    bundle.chmod(0o600)
    return report, bundle


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only Salesforce Flow version and Stats field audit.")
    parser.add_argument("--org", default="work")
    parser.add_argument("--flow-name", default="",
                        help="Exact API name if multiple matching Flows exist.")
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
    except (FlowAuditError, OSError) as exc:
        print("Flow audit failed (no Salesforce writes): " + str(exc),
              file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    print("READ-ONLY AUDIT BUNDLE: " + str(path))
    print("Share the ZIP privately for exact Flow v30 vs Stats comparison.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
