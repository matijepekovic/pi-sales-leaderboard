#!/usr/bin/env bash
# Read-only export of the exact Result Appointment Flow v30 and field metadata.
# No Salesforce record or Flow is run, activated, modified or deployed.
set -euo pipefail
umask 077

ORG="${1:-work}"
command -v sf >/dev/null || { echo "Salesforce CLI (sf) is not installed." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required." >&2; exit 1; }
OUT="$(mktemp -d "${HOME}/stats-flow-v30.XXXXXXXX")"
echo "Read-only Salesforce audit. Private export directory: $OUT"

sf data query --use-tooling-api --target-org "$ORG" --json \
  --query "SELECT Id, MasterLabel, VersionNumber, Status FROM Flow WHERE VersionNumber = 30 AND MasterLabel LIKE '%Result%Appointment%'" \
  > "$OUT/flow-candidates.json"

FLOW_ID="$(python3 - "$OUT/flow-candidates.json" <<'PY'
import json
import re
import sys
value = json.load(open(sys.argv[1], encoding='utf-8'))
if value.get('status') not in (0, None):
    sys.exit('Tooling API query failed.')
rows = (value.get('result') or {}).get('records', [])
if not isinstance(rows, list):
    sys.exit('Unexpected Tooling API response.')
rows = [
    row for row in rows
    if isinstance(row, dict)
    and str(row.get('VersionNumber')) == '30'
    and 'result' in str(row.get('MasterLabel', '')).casefold()
    and 'appointment' in str(row.get('MasterLabel', '')).casefold()
]
if len(rows) != 1:
    print('Expected one Result Appointment v30 Flow, found:', len(rows), file=sys.stderr)
    for row in rows:
        print('  ', row.get('MasterLabel'), 'version',
              row.get('VersionNumber'), row.get('Status'), file=sys.stderr)
    sys.exit('No Flow was guessed. Check Flow labels/permissions.')
ident = str(rows[0].get('Id', ''))
if not re.fullmatch(r'[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?', ident):
    sys.exit('Unexpected Tooling Flow record ID.')
print(ident)
PY
)"

# Use the Tooling API record ID to read v30 itself, not a metadata retrieve
# that could return the active/latest version instead.
sf api request rest "/services/data/v65.0/tooling/sobjects/Flow/${FLOW_ID}" \
  --method GET --target-org "$ORG" --json > "$OUT/flow-v30.json"

python3 - "$OUT/flow-v30.json" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding='utf-8'))
record = value.get('result', value)
if not isinstance(record, dict) or int(record.get('VersionNumber') or 0) != 30:
    sys.exit('Wrong Flow version. Export discarded from verification.')
if not isinstance(record.get('Metadata'), dict) or not record['Metadata']:
    sys.exit('Flow metadata unavailable. Read permissions may be missing.')
print('Confirmed:', record.get('MasterLabel'), 'version 30 /',
      record.get('Status', 'unknown'))
PY

for object in WorkOrder Lead ServiceAppointment Product_Interest_Result__c; do
  sf sobject describe --sobject "$object" --target-org "$ORG" --json \
    > "$OUT/describe-${object}.json"
done

if python3 -c "import printer_app.mod_resulting.flow_audit" >/dev/null 2>&1; then
  python3 -m printer_app.mod_resulting.flow_audit \
    --flow "$OUT/flow-v30.json" --schema-dir "$OUT" --org "$ORG" \
    --json-report "$OUT/audit-report.json" | tee "$OUT/audit-summary.txt"
else
  echo "Stats audit module unavailable in this working directory."
  echo "Flow and field metadata were still saved. Update the Stats source to run the audit."
fi
echo "Private read-only exports: $OUT"
echo "Share audit-summary.txt for comparison. Keep raw Flow and describe JSON private."
