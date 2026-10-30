"""Read-only Flow v30 evidence collection must never submit MOD results."""
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


FLOW_XML = b"""<?xml version="1.0"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
  <apiVersion>68.0</apiVersion><status>Active</status>
  <processType>Flow</processType>
  <decisions><name>Choose_Primary</name><label>Choose Primary</label>
    <rules><name>IsToday</name><conditionLogic>and</conditionLogic>
      <conditions><leftValueReference>Lead.Appointment_Date__c</leftValueReference>
        <operator>EqualTo</operator><rightValue><stringValue>today</stringValue></rightValue>
      </conditions>
    </rules>
  </decisions>
  <recordUpdates><name>Update_Result</name>
    <object>Product_Interest_Result__c</object>
    <inputAssignments><field>Include_in_Issued_Lead_Count__c</field>
      <value><booleanValue>true</booleanValue></value></inputAssignments>
  </recordUpdates>
</Flow>"""


def test_readonly_cli_rejects_every_write_family_even_if_live_writes_enabled(monkeypatch):
    monkeypatch.setenv("MOD_RESULTING_LIVE_WRITES", "1")
    invoked = []
    def fail_if_called(*_args, **_kwargs):
        invoked.append(1)
        raise AssertionError("No Salesforce process should have started")
    cli = ReadOnlySalesforceCLI(runner=fail_if_called)
    for operation in (
        ["data", "update", "record"], ["data", "create", "record"],
        ["data", "delete", "record"], ["project", "deploy", "start"],
        ["apex", "run"], ["flow", "run"], ["org", "open"],
    ):
        with pytest.raises(FlowAuditError, match="Forbidden"):
            cli.call(operation)
    assert invoked == []


def test_pick_exact_result_appointment_flow_and_refuse_ambiguous_names():
    rows = [{"fullName":"Result_Appointment"}]
    assert select_flow(rows, [], "") == "Result_Appointment"
    assert select_flow(rows, [], "Result_Appointment") == "Result_Appointment"
    with pytest.raises(FlowAuditError, match="Multiple"):
        select_flow(rows + [{"fullName":"Result_Appointment_v2"}], [], "")
    with pytest.raises(FlowAuditError, match="not found"):
        select_flow(rows, [], "Not_The_Flow")
    with pytest.raises(FlowAuditError, match="Invalid"):
        select_flow(rows, [], "Flow:Other*")
    assert select_flow([], [{"ApiName":"X30", "Label":"Result Appointment Flow"}]) == "X30"


def test_flow_inventory_includes_actual_branches_and_fields():
    inventory = flow_inventory(FLOW_XML)
    assert inventory["flow_status"] == "Active"
    assert inventory["api_version"] == "68.0"
    assert inventory["element_counts"] == {"decisions":1, "recordUpdates":1}
    decision, update = inventory["elements"]
    assert decision["rules"][0]["conditions"][0]["left"] == (
        "Lead.Appointment_Date__c")
    assert decision["rules"][0]["conditions"][0]["operator"] == "EqualTo"
    assert update["assigned_fields"] == [PR_ISSUED_COUNT]
    assert update["object"] == PRODUCT_RESULT
    with pytest.raises(FlowAuditError, match="DTD"):
        flow_inventory(b"<!DOCTYPE Flow><Flow />")
    with pytest.raises(FlowAuditError, match="not a Salesforce Flow"):
        flow_inventory(b"<AnotherObject />")


def test_field_inventory_uses_existing_salesforce_adapter_contract():
    requirements = field_requirements()
    assert PR_ISSUED_COUNT in requirements[PRODUCT_RESULT]
    assert PR_APPOINTMENT_DATE in requirements[PRODUCT_RESULT]
    field_data = relevant_fields({"fields":[
        {"name":PR_ISSUED_COUNT, "type":"boolean",
         "createable":False, "updateable":True, "picklistValues":[]},
    ]}, requirements[PRODUCT_RESULT])
    assert field_data[PR_ISSUED_COUNT] == {
        "present": True, "type":"boolean", "createable":False,
        "updateable":True, "referenceTo":[], "picklistValues":[],
    }
    assert field_data[PR_APPOINTMENT_DATE] == {"present":False}


def test_full_audit_only_reads_metadata_and_retrieves_explicit_version(tmp_path, monkeypatch):
    monkeypatch.setenv("MOD_RESULTING_LIVE_WRITES", "1")
    commands = []
    def runner(command, **kwargs):
        commands.append(command)
        assert command[:1] == ["sf"]
        assert command[-3:] == ["--target-org", "work", "--json"]
        assert "--json" in command
        if command[1:4] == ["data","query","--query"]:
            query = command[command.index("--query") + 1]
            assert "FROM FlowDefinitionView" in query
            result = {"records":[{
                "Id":"301000000000001AAA",
                "ApiName":"Result_Appointment", "Label":"Result Appointment",
                "ActiveVersionId":"301000000000030AAA",
                "LatestVersionId":"301000000000030AAA", "VersionNumber":30,
            }], "done":True}
        elif command[1:4] == ["org","list","metadata"]:
            result = [{"fullName":"Result_Appointment",
                       "fileName":"flows/Result_Appointment.flow"}]
        elif command[1:4] == ["sobject","describe","--sobject"]:
            object_name = command[command.index("--sobject") + 1]
            fields = []
            for name in field_requirements()[object_name]:
                fields.append({"name":name,
                               "type": ("boolean" if name == PR_ISSUED_COUNT
                                        else "date" if name == PR_APPOINTMENT_DATE
                                        else "string"),
                               "updateable":True, "createable":True,
                               "picklistValues":[]})
            result = {"name":object_name, "fields":fields}
        elif command[1:4] == ["project","retrieve","start"]:
            assert command[command.index("--metadata") + 1] == (
                "Flow:Result_Appointment-30")
            base = Path(command[command.index("--output-dir") + 1])
            flow = base/"force-app/main/default/flows/Result_Appointment-30.flow-meta.xml"
            flow.parent.mkdir(parents=True)
            flow.write_bytes(FLOW_XML)
            result = {"files":[{"fullName":"Result_Appointment-30"}]}
        else:
            raise AssertionError("Unexpected Salesforce operation: " + str(command))
        return SimpleNamespace(
            stdout=json.dumps({"status":0,"result":result}),
            returncode=0, stderr="",
        )

    destination = tmp_path / "audit"
    summary, bundle = collect(output=destination, runner=runner)
    assert summary["mode"] == "read_only"
    assert summary["salesforce_records_read"] == 0
    assert summary["salesforce_records_modified"] == 0
    assert summary["parity_verified"] is False
    assert summary["flow_version_requested"] == 30
    assert summary["phase3_critical_fields"][PR_ISSUED_COUNT]["writable"] is True
    assert bundle.exists() and bundle.stat().st_size > 100
    assert not (destination / "_temporary_salesforce_project").exists()
    assert not any(
        command[1:3] in (["data","update"], ["data","create"], ["data","delete"],
                          ["project","deploy"]) for command in commands)
    assert len([command for command in commands if command[1:3] ==
                ["sobject","describe"]]) == 4
    with zipfile.ZipFile(bundle) as z:
        assert z.read("flow_version_30.xml") == FLOW_XML
        assert "stats_field_metadata.json" in z.namelist()
        assert json.loads(z.read("summary.json"))["parity_verified"] is False


def test_missing_explicit_version_never_uses_latest_flow(tmp_path):
    def runner(command, **kwargs):
        if command[1:3] == ["project","retrieve"]:
            # Salesforce provided only a nonmatching component.
            bad = Path(command[command.index("--output-dir")+1]) / (
                "force-app/main/default/flows/Another_Flow.flow-meta.xml")
            bad.parent.mkdir(parents=True)
            bad.write_bytes(FLOW_XML)
            result = {}
        else:
            result = []
        return SimpleNamespace(stdout=json.dumps({"status":0,"result":result}),
                               returncode=0, stderr="")
    project = tmp_path / "project"
    project.mkdir()
    cli = ReadOnlySalesforceCLI(runner=runner)
    with pytest.raises(FlowAuditError, match="not uniquely retrieved"):
        cli.retrieve_flow("Result_Appointment", 30, project)
