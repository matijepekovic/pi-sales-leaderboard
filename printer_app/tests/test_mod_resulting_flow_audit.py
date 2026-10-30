"""Flow v30 audit reads Tooling metadata without executing any resulting writes."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from printer_app.mod_resulting.flow_audit import (
    FlowAuditError, ReadOnlySalesforceCLI, collect, field_requirements,
    flow_inventory, relevant_fields, select_flow,
)
from printer_app.mod_resulting.salesforce_adapter import (
    PR_APPOINTMENT_DATE, PR_ISSUED_COUNT, PRODUCT_RESULT,
)


FLOW_ID = "301000000000030AAA"
FLOW_VERSIONS = [{
    "Id": FLOW_ID,
    "Definition": {"DeveloperName": "Result_Appointment"},
    "MasterLabel": "Result Appointment",
    "VersionNumber": 30,
    "Status": "Active",
}]
FLOW_METADATA = {
    "apiVersion": 68.0,
    "status": "Active",
    "processType": "Flow",
    "decisions": [{
        "name": "Choose_Primary",
        "label": "Choose Primary",
        "rules": [{
            "name": "IsToday",
            "conditionLogic": "and",
            "conditions": [{
                "leftValueReference": "Lead.Appointment_Date__c",
                "operator": "EqualTo",
                "rightValue": {"stringValue": "today"},
            }],
        }],
    }],
    "recordUpdates": [{
        "name": "Update_Result",
        "object": PRODUCT_RESULT,
        "inputAssignments": [{
            "field": PR_ISSUED_COUNT,
            "value": {"booleanValue": True},
        }],
    }],
}


def test_allowlist_blocks_data_writes_even_when_live_writes_are_on(monkeypatch):
    monkeypatch.setenv("MOD_RESULTING_LIVE_WRITES", "1")
    invoked = []
    def impossible(*_args, **_kwargs):
        invoked.append(True)
        raise AssertionError("No shell command should run")
    cli = ReadOnlySalesforceCLI(runner=impossible)
    for operation in (
        ["data", "update", "record"], ["data", "create", "record"],
        ["data", "delete", "record"], ["project", "deploy", "start"],
        ["project", "retrieve", "start"], ["org", "list", "metadata"],
        ["apex", "run"], ["flow", "run"], ["org", "open"],
    ):
        with pytest.raises(FlowAuditError, match="Forbidden"):
            cli.call(operation)
    assert invoked == []


def test_select_exact_version_and_refuse_ambiguity_or_unknown_product():
    assert select_flow(FLOW_VERSIONS, 30)["name"] == "Result_Appointment"
    assert select_flow(FLOW_VERSIONS, 30, "Result_Appointment")["id"] == FLOW_ID
    with pytest.raises(FlowAuditError, match="version 29"):
        select_flow(FLOW_VERSIONS, 29)
    with pytest.raises(FlowAuditError, match="version 30"):
        select_flow(FLOW_VERSIONS, 30, "Not_The_Flow")
    with pytest.raises(FlowAuditError, match="Invalid Flow"):
        select_flow(FLOW_VERSIONS, 30, "Flow:Other*")
    with pytest.raises(FlowAuditError, match="found 2"):
        select_flow(FLOW_VERSIONS + [{
            **FLOW_VERSIONS[0], "Id": "301000000000031AAA",
            "Definition": {"DeveloperName": "Result_Appointment_v2"},
        }], 30)
    assert select_flow([{
        **FLOW_VERSIONS[0], "Definition": {"DeveloperName": "X30"},
    }], 30, "X30")["name"] == "X30"


def test_inventory_reads_actual_tooling_decision_and_field_assignment():
    inventory = flow_inventory(FLOW_METADATA)
    assert inventory["flow_status"] == "Active"
    assert inventory["process_type"] == "Flow"
    assert inventory["api_version"] == 68.0
    assert inventory["element_counts"] == {
        "decisions": 1, "recordUpdates": 1
    }
    decision, update = inventory["elements"]
    assert decision["rules"][0]["conditions"][0]["leftValueReference"] == (
        "Lead.Appointment_Date__c"
    )
    assert update["assigned_fields"] == [PR_ISSUED_COUNT]
    assert update["object"] == PRODUCT_RESULT
    with pytest.raises(FlowAuditError, match="must be an object"):
        flow_inventory("not-a-metadata-object")


def test_relevant_fields_derive_from_existing_salesforce_adapter():
    requirements = field_requirements()
    assert {PR_ISSUED_COUNT, PR_APPOINTMENT_DATE} <= requirements[PRODUCT_RESULT]
    f = relevant_fields({"fields":[
        {"name":PR_ISSUED_COUNT, "type":"boolean",
         "createable":False, "updateable":True, "picklistValues":[]},
    ]}, requirements[PRODUCT_RESULT])
    assert f[PR_ISSUED_COUNT] == {
        "present": True, "type": "boolean", "createable": False,
        "updateable": True, "referenceTo": [], "picklistValues": [],
    }
    assert f[PR_APPOINTMENT_DATE] == {"present":False}


def _fake_runner(commands, *, missing=False, bad_version=False):
    def runner(command, **kwargs):
        commands.append(command)
        assert command[0] == "sf"
        assert command[-3:] == ["--target-org", "work", "--json"]
        assert not any(
            command[1:3] == operation
            for operation in (
                ["data","update"], ["data","create"], ["data","delete"],
                ["project","deploy"], ["project","retrieve"],
            )
        )
        if command[1:3] == ["data","query"]:
            assert "--use-tooling-api" in command
            soql = command[command.index("--query") + 1]
            if "VersionNumber = 30" in soql:
                result = {"records": [] if bad_version else FLOW_VERSIONS,
                          "done": True}
            elif "WHERE Id = '" + FLOW_ID + "'" in soql:
                assert "SELECT Id, Metadata" in soql
                result = {"records":[{"Id":FLOW_ID,"Metadata":FLOW_METADATA}],
                          "done":True}
            else:
                raise AssertionError("Unexpected read-only Tooling query")
        elif command[1:3] == ["sobject","describe"]:
            name = command[command.index("--sobject") + 1]
            fields = [{
                "name":field_name,
                "type": ("boolean" if field_name == PR_ISSUED_COUNT
                         else "date" if field_name == PR_APPOINTMENT_DATE
                         else "string"),
                "updateable":True, "createable":True,
                "picklistValues":[],
            } for field_name in field_requirements()[name]]
            result = {"name":name,"fields":fields}
        else:
            raise AssertionError("Unexpected Salesforce operation")
        response = (
            {"status":1,"name":"INSUFFICIENT_ACCESS",
             "message":"Your user cannot read Tooling Flow metadata"}
            if missing else {"status":0,"result":result}
        )
        return SimpleNamespace(
            stdout=json.dumps(response),
            returncode=1 if missing else 0,
            stderr="",
        )
    return runner


def test_full_audit_uses_exact_flow_id_and_only_read_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("MOD_RESULTING_LIVE_WRITES", "1")
    calls = []
    summary, bundle = collect(
        output=tmp_path/"flow-audit", runner=_fake_runner(calls))
    assert summary["mode"] == "read_only"
    assert summary["salesforce_customer_records_read"] == 0
    assert summary["salesforce_records_modified"] == 0
    assert summary["parity_verified"] is False
    assert summary["flow_version_requested"] == 30
    assert summary["flow_version_confirmed"] is True
    assert summary["flow_version_record_id"] == FLOW_ID
    assert summary["version_30_active"] is True
    assert summary["source"] == "Tooling_API_Flow_by_exact_version_id"
    assert summary["phase3_critical_fields"][PR_ISSUED_COUNT]["writable"] is True
    assert bundle.exists() and bundle.stat().st_size > 100
    assert len(calls) == 6
    assert len([c for c in calls if c[1:3] == ["sobject","describe"]]) == 4
    assert len([c for c in calls if c[1:3] == ["data","query"]]) == 2
    assert not any("Flow:" in " ".join(c) for c in calls)
    with zipfile.ZipFile(bundle) as z:
        assert json.loads(z.read("flow_version_30.json")) == FLOW_METADATA
        assert json.loads(z.read("summary.json"))["parity_verified"] is False


def test_bad_version_and_tooling_permission_error_are_explicit(tmp_path):
    calls = []
    with pytest.raises(FlowAuditError, match="version 30"):
        collect(output=tmp_path/"missing",runner=_fake_runner(calls,bad_version=True))
    assert all(c[1:3] not in (["data","create"],["data","update"])
               for c in calls)

    calls = []
    with pytest.raises(FlowAuditError, match="INSUFFICIENT_ACCESS"):
        collect(output=tmp_path/"denied",runner=_fake_runner(calls,missing=True))
    assert all(c[1:3] not in (["data","create"],["data","update"])
               for c in calls)


def test_tooling_metadata_can_not_fall_back_to_another_flow_version():
    commands = []
    def runner(command, **kwargs):
        commands.append(command)
        if "VersionNumber = 30" in " ".join(command):
            result = {"records":FLOW_VERSIONS,"done":True}
        else:
            result = {"records":[{
                "Id":"301000000000032AAA","Metadata":FLOW_METADATA
            }],"done":True}
        return SimpleNamespace(stdout=json.dumps({"status":0,"result":result}),
                               returncode=0,stderr="")
    cli = ReadOnlySalesforceCLI(runner=runner)
    with pytest.raises(FlowAuditError, match="Exact Flow version"):
        cli.flow_metadata(FLOW_ID)
    assert len(commands) == 1
