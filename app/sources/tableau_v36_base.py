"""
Tableau connector for the Olympia Pi sales leaderboard.

Tableau is only the sales-data source. The Raspberry Pi remains the
organization layer: local team assignments, team leads, logos and display
configuration never get written back to Tableau and are not erased by a pull.

The Tableau target is intentionally fixed for this installation:

    server      https://10ay.online.tableau.com
    site        dabella
    workbook    8-SalesRepLevelData
    view        RepTotals
    PAT name    leaderboard
    Home Branch Olympia
    date fields Start / End

Only the PAT secret is supplied by the user. Start/End normally follow the
current calendar month, with an optional persistent manual override stored in
the Pi settings database.

COUNTING RULES
--------------
The export is lead-level and can be long-format (Measure Names / Measure
Values). A sold lead with multiple products can therefore appear on multiple
job rows. Counting metrics are taken once per LEAD-Id while dollar metrics
sum across job rows. Tableau's per-rep "All" roll-up rows are skipped.
"""
import csv
import io
import json
import re
from datetime import date
import urllib.error
import urllib.parse
import urllib.request

from .base import LeaderboardSource

# ---------------------------------------------------------------- fixed Tableau target

TABLEAU_SERVER = "https://10ay.online.tableau.com"
TABLEAU_SITE = "dabella"
TABLEAU_PAT_NAME = "leaderboard"
TABLEAU_WORKBOOK_CONTENT_URL = "8-SalesRepLevelData"
TABLEAU_VIEW_URL_NAME = "RepTotals"
TABLEAU_VIEW_PATH = f"{TABLEAU_WORKBOOK_CONTENT_URL}/{TABLEAU_VIEW_URL_NAME}"
TABLEAU_HOME_BRANCH = "Olympia"
TABLEAU_START_FIELD = "Start"
TABLEAU_END_FIELD = "End"
# The filter card is titled "Home Branch", but the field in the RepTotals data
# is USER-Home Branch. Tableau REST view filters require the underlying field
# key, not the display title of the filter card.
TABLEAU_HOME_BRANCH_FIELD = "USER-Home Branch"

# ---------------------------------------------------------------- mapping

FIELD_ALIASES = {
    "issuedLeads":    ["issuedleads", "leadsissued", "issued"],
    "pitchedLeads":   ["pitchedleads", "leadspitched", "pitched"],
    "pitchRate":      ["pitchedrate", "pitchrate", "pitchpct", "pitchpercent"],
    "soldLeads":      ["soldleads", "leadssold", "sold"],
    "closeRate":      ["closerate", "closingrate", "closepct", "closepercent"],
    "grossSplit":     ["grosssplit", "grosssales", "grossvolume", "gross"],
    "netSplit":       ["netsplit", "netsales", "netvolume"],
    "pendingSplit":   ["pendingsplit", "pending"],
    "dpl":            ["dollarsperlead", "dpl", "perlead"],
    "salesRetention": ["salesretention", "retentionrate", "retention"],
    "avgGrossPerRep": ["avggrosssaleperrep", "avggrossperrep", "averagegrossperrep", "avggross"],
    "avgNetPerRep":   ["avgnetsaleperrep", "avgnetperrep", "averagenetperrep", "avgnet"],
}
ALIAS_INDEX = sorted(
    ((a, f) for f, aliases in FIELD_ALIASES.items() for a in aliases),
    key=lambda p: -len(p[0])
)

REP_ALIASES = ["srname", "rep", "repname", "salesrep", "salesperson",
               "employee", "assignedrep"]
# Prefer the human-readable USER-Home Branch (Olympia) over Branch-New
# (WA-OLY) when both are present in the export. Prefix matching below also
# handles Salesforce-ish captions such as USER-Home Branch Picklist__c.
BRANCH_ALIASES = ["userhomebranch", "homebranch", "branchnew", "branch",
                  "office", "location", "market"]
TITLE_ALIASES = ["usertitlepicklist", "title", "position"]
HIRE_ALIASES = ["hiredate", "hire"]
TEAM_ALIASES = ["teamleadname", "teamlead", "team"]
LEAD_ID_ALIASES = ["leadid"]
MEASURE_NAME_COLS = ["measurenames", "measure"]
MEASURE_VALUE_COLS = ["measurevalues", "value"]

PCT_FIELDS = {"pitchRate", "closeRate", "salesRetention"}
MEAN_FIELDS = PCT_FIELDS | {"dpl", "avgGrossPerRep", "avgNetPerRep"}
COUNT_FIELDS = {"issuedLeads", "pitchedLeads", "soldLeads"}

SCHEMA_MAP = {
    "issuedLeads": "issued_leads",
    "pitchedLeads": "pitched_leads",
    "pitchRate": "pitched_rate",
    "soldLeads": "sold_leads",
    "closeRate": "close_rate",
    "grossSplit": "gross_split",
    "pendingSplit": "pending_split",
    "netSplit": "net_split",
    "dpl": "dpl",
    "salesRetention": "sales_retention",
    "avgGrossPerRep": "avg_gross_sale",
    "avgNetPerRep": "avg_net_sale",
}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def clean_number(raw):
    """'$48,750' -> 48750.0 ; '82%' -> 82.0 ; '' -> None."""
    if raw is None:
        return None
    s = str(raw).strip().replace("$", "").replace(",", "").replace("%", "")
    if s in ("", "-", "—", "n/a", "null", "None"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def match_field(header_norm):
    """Longest-alias-first substring match, so 'AGG(Pitch Rate)' still maps."""
    if not header_norm:
        return None
    for alias, field in ALIAS_INDEX:
        if alias in header_norm:
            return field
    return None


def find_column(headers, aliases):
    """
    Find an export column by exact normalized name first, then by a conservative
    prefix/substring match. Tableau often exposes the same workbook field with
    a longer Salesforce caption than the dashboard filter-card title.
    """
    normalized = [(header, norm(header)) for header in (headers or [])]
    for alias in aliases:
        for header, value in normalized:
            if value == alias:
                return header
    for alias in aliases:
        for header, value in normalized:
            if value.startswith(alias) or alias in value:
                return header
    return None


def derive(r):
    """Fill missing computed columns without overwriting Tableau values."""
    def put(key, val):
        if r.get(key) is None:
            r[key] = val

    issued, pitched = r.get("issuedLeads"), r.get("pitchedLeads")
    sold = r.get("soldLeads")
    gross, net = r.get("grossSplit"), r.get("netSplit")
    if issued and pitched is not None:
        put("pitchRate", pitched / issued * 100.0)
    if issued and sold is not None:
        put("closeRate", sold / issued * 100.0)
    if issued and net is not None:
        put("dpl", net / issued)
    if gross and net is not None:
        put("salesRetention", net / gross * 100.0)
    if sold:
        if gross is not None:
            put("avgGrossPerRep", gross / sold)
        if net is not None:
            put("avgNetPerRep", net / sold)
    return r


def rep_key_for(name):
    key = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
    return key or "unknown"


# ---------------------------------------------------------------- parsing
def parse_rows(csv_text):
    """Parse Tableau view-data CSV into camelCase rep dictionaries."""
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = reader.fieldnames or []

    def col_for(aliases):
        return find_column(headers, aliases)

    rep_col = col_for(REP_ALIASES)
    if not rep_col:
        raise ValueError(
            "Could not find a rep-name column in the Tableau data. "
            f"Columns seen: {', '.join(headers) or '(none)'}"
        )
    branch_col = col_for(BRANCH_ALIASES)
    title_col = col_for(TITLE_ALIASES)
    hire_col = col_for(HIRE_ALIASES)
    team_col = col_for(TEAM_ALIASES)
    lead_col = col_for(LEAD_ID_ALIASES)
    mn_col = col_for(MEASURE_NAME_COLS)
    mv_col = col_for(MEASURE_VALUE_COLS)
    long_fmt = bool(mn_col and mv_col)
    hmap = {h: norm(h) for h in headers}

    acc = {}
    meta = {}
    order = []

    for row in reader:
        name = (row.get(rep_col) or "").strip()
        if not name:
            continue
        if name not in acc:
            acc[name] = {}
            meta[name] = {}
            order.append(name)

        lead = (row.get(lead_col) or "").strip() if lead_col else ""
        if long_fmt and lead.lower() == "all":
            continue

        info = meta[name]
        for key, col in (("home_branch", branch_col), ("title", title_col),
                         ("hire_date", hire_col), ("team", team_col)):
            if col:
                val = (row.get(col) or "").strip()
                if val and val.lower() != "all" and not info.get(key):
                    info[key] = val

        def feed(field, raw):
            v = clean_number(raw)
            if v is None:
                return
            if long_fmt and field in COUNT_FIELDS and lead:
                acc[name].setdefault(field, {}).setdefault(lead, v)
            else:
                slot = acc[name].setdefault(field, [0.0, 0])
                slot[0] += v
                slot[1] += 1

        if long_fmt:
            field = match_field(norm(row.get(mn_col) or ""))
            if field:
                feed(field, row.get(mv_col))
        else:
            for h, n in hmap.items():
                field = match_field(n)
                if field:
                    feed(field, row.get(h))

    reps = []
    for name in order:
        rec = {"name": name}
        for field, agg in acc[name].items():
            if isinstance(agg, dict):
                rec[field] = sum(agg.values())
            else:
                total, count = agg
                rec[field] = (total / count) if field in MEAN_FIELDS and count else total
        rec.update(meta[name])
        reps.append(derive(rec))
    return reps


def to_app_rows(reps):
    """camelCase parser dictionaries -> app rep schema."""
    rows = []
    for r in reps:
        row = {
            "rep_key": rep_key_for(r["name"]),
            "rep_name": r["name"],
            "team": r.get("team") or "Unassigned",
            "home_branch": r.get("home_branch") or "",
            "title": r.get("title") or "",
            "hire_date": r.get("hire_date") or "",
        }
        for camel, snake in SCHEMA_MAP.items():
            row[snake] = r.get(camel) or 0
        rows.append(row)
    return rows


def branch_profile(csv_text):
    """Return (exact export header, distinct nonblank branch values)."""
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = reader.fieldnames or []
    branch_col = find_column(headers, BRANCH_ALIASES)
    values = set()
    if branch_col:
        for row in reader:
            value = str(row.get(branch_col) or "").strip()
            if value and value.lower() != "all":
                values.add(value)
    return branch_col, values


# ---------------------------------------------------------------- dates
def month_range(today=None):
    """First and last day of the current month as YYYY-MM-DD."""
    today = today or date.today()
    first = today.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1)
    else:
        nxt = first.replace(month=first.month + 1)
    last = nxt.toordinal() - 1
    return first.isoformat(), date.fromordinal(last).isoformat()


def resolve_dates(settings, today=None):
    """Current month unless a complete manual override is active."""
    if str(settings.get("data_date_mode") or "current_month") == "custom":
        start = str(settings.get("data_date_start") or "").strip()
        end = str(settings.get("data_date_end") or "").strip()
        if start and end:
            return start, end
    return month_range(today)


# ---------------------------------------------------------------- Tableau IO
class TableauError(RuntimeError):
    pass


def why_failed(status, raw):
    """Tableau's own reason for a refused call, short enough for a phone.

    A failed sign-in and a token that cannot browse content are both a bare
    401 or 403 otherwise, which is no help at all when the settings page has
    to tell someone what to fix. Tableau answers with a code/summary/detail
    block; this reduces it to one line and falls back to the status when the
    body is not that shape. Only Tableau's own words come back, never
    anything the caller sent, so a PAT secret cannot ride out in an error.
    """
    detail = ""
    try:
        error = json.loads(raw).get("error", {})
        code = str(error.get("code") or "").strip()
        words = " ".join(part for part in (str(error.get("summary") or "").strip(),
                                           str(error.get("detail") or "").strip())
                         if part)
        detail = f"{code} {words}".strip()
    except Exception:
        detail = ""
    detail = " ".join(detail.split())[:200]
    return f"HTTP {status}" + (f" - {detail}" if detail else "")


class TableauSource(LeaderboardSource):
    SERVER = TABLEAU_SERVER
    SITE = TABLEAU_SITE
    PAT_NAME = TABLEAU_PAT_NAME
    VIEW_PATH = TABLEAU_VIEW_PATH
    OFFICE = TABLEAU_HOME_BRANCH

    def __init__(self, config=None):
        self.config = config or {}
        self.last_offices = []
        self.last_total_rows = 0
        self.last_remote_rows = 0
        self.last_branch_filter_field = ""
        self.branch_filter_guard_used = False

    def _pat_secret(self):
        return str(self.config.get("tableau_pat_secret") or "").strip()

    def _request(self, url, method="GET", token=None, body=None, timeout=60):
        headers = {
            "Accept": "application/json",
            "User-Agent": "pi-tableau-sales-leaderboard",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["X-Tableau-Auth"] = token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except urllib.error.URLError as exc:
            raise TableauError(f"Could not reach Tableau: {exc.reason}")

    def _api_base(self):
        version = "3.22"
        status, raw = self._request(f"{TABLEAU_SERVER}/api/{version}/serverinfo", timeout=20)
        if status == 200:
            try:
                version = json.loads(raw)["serverInfo"]["restApiVersion"]
            except Exception:
                pass
        return f"{TABLEAU_SERVER}/api/{version}"

    def signin(self):
        pat_secret = self._pat_secret()
        if not pat_secret:
            raise TableauError("Enter the Tableau PAT secret on the Pi first.")

        base = self._api_base()
        status, raw = self._request(
            f"{base}/auth/signin",
            method="POST",
            body={"credentials": {
                "personalAccessTokenName": TABLEAU_PAT_NAME,
                "personalAccessTokenSecret": pat_secret,
                "site": {"contentUrl": TABLEAU_SITE},
            }},
        )
        if status != 200:
            raise TableauError(
                f"Tableau sign-in failed ({why_failed(status, raw)}). "
                f"Check the PAT secret for token 'leaderboard'."
            )
        try:
            creds = json.loads(raw)["credentials"]
            return base, creds["token"], creds["site"]["id"]
        except Exception as exc:
            raise TableauError("Tableau sign-in returned an unexpected response.") from exc

    def signout(self, base, token):
        try:
            self._request(f"{base}/auth/signout", method="POST", token=token)
        except Exception:
            pass

    @staticmethod
    def _view_list(payload):
        """Handle Tableau's list/single-object JSON shapes defensively."""
        if not isinstance(payload, dict):
            return []
        views = payload.get("views", {}).get("view", [])
        if isinstance(views, dict):
            return [views]
        if isinstance(views, list):
            return views
        view = payload.get("view")
        if isinstance(view, dict):
            return [view]
        return []

    def _workbook_id(self, base, token, site_id):
        workbook_key = urllib.parse.quote(TABLEAU_WORKBOOK_CONTENT_URL, safe="")
        status, raw = self._request(
            f"{base}/sites/{site_id}/workbooks/{workbook_key}?key=contentUrl",
            token=token,
        )
        if status != 200:
            raise TableauError(
                f"Could not find Tableau workbook '{TABLEAU_WORKBOOK_CONTENT_URL}' "
                f"(HTTP {status})."
            )
        try:
            workbook = json.loads(raw).get("workbook", {})
            workbook_id = str(workbook.get("id") or "").strip()
        except Exception:
            workbook_id = ""
        if not workbook_id:
            raise TableauError(
                f"Tableau workbook '{TABLEAU_WORKBOOK_CONTENT_URL}' returned no workbook id."
            )
        return workbook_id

    def _view_id(self, base, token, site_id):
        """Resolve the normal RepTotals view; custom views are never used."""
        workbook_id = self._workbook_id(base, token, site_id)
        status, raw = self._request(
            f"{base}/sites/{site_id}/workbooks/{workbook_id}/views",
            token=token,
        )
        if status != 200:
            raise TableauError(f"Could not list views for {TABLEAU_WORKBOOK_CONTENT_URL}.")
        try:
            views = self._view_list(json.loads(raw))
        except Exception:
            views = []

        target_url = TABLEAU_VIEW_URL_NAME.lower()
        target_content_tail = f"/{TABLEAU_VIEW_URL_NAME}".lower()
        for view in views:
            view_url_name = str(view.get("viewUrlName") or "").strip().lower()
            name = str(view.get("name") or "").strip().lower()
            content_url = str(view.get("contentUrl") or "").strip().lower()
            if (view_url_name == target_url
                    or name == target_url
                    or content_url.endswith(target_content_tail)
                    or content_url.endswith(f"/sheets{target_content_tail}")):
                view_id = str(view.get("id") or "").strip()
                if view_id:
                    return view_id

        visible = ", ".join(
            str(v.get("viewUrlName") or v.get("name") or v.get("contentUrl") or "?")
            for v in views[:20]
        ) or "(none visible)"
        raise TableauError(
            f"Normal view '{TABLEAU_VIEW_PATH}' was not found. Visible workbook views: {visible}"
        )

    def _query_view_csv(self, base, token, site_id, view_id, start, end, branch_field):
        params = {
            "maxAge": "1",
            f"vf_{TABLEAU_START_FIELD}": start,
            f"vf_{TABLEAU_END_FIELD}": end,
            f"vf_{branch_field}": TABLEAU_HOME_BRANCH,
        }
        # Use %20 rather than '+' in field names. Tableau documents view-filter
        # keys with percent-encoded spaces.
        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        status, raw = self._request(
            f"{base}/sites/{site_id}/views/{view_id}/data?{query}",
            token=token,
        )
        if status != 200:
            raise TableauError(
                f"Tableau data request failed (HTTP {status}) for "
                f"{TABLEAU_VIEW_PATH}, {TABLEAU_HOME_BRANCH}, {start} to {end}."
            )
        return raw.decode("utf-8-sig", errors="replace")

    def fetch_csv(self, base, token, site_id, start, end):
        """
        Pull RepTotals with Start/End and the Olympia home-branch filter.

        Tableau requires the underlying field key. We first use the known
        USER-Home Branch field. If Tableau returns more than Olympia, inspect
        the CSV header it returned and retry once using the exact export
        caption. This handles workbook caption changes without reverting to a
        custom view.
        """
        view_id = self._view_id(base, token, site_id)
        candidates = [TABLEAU_HOME_BRANCH_FIELD, "Home Branch"]
        tried = set()
        last_csv = ""

        for candidate in candidates:
            key = str(candidate or "").strip()
            if not key or key.lower() in tried:
                continue
            tried.add(key.lower())

            csv_text = self._query_view_csv(
                base, token, site_id, view_id, start, end, key
            )
            last_csv = csv_text
            branch_col, branch_values = branch_profile(csv_text)
            office = TABLEAU_HOME_BRANCH.lower()

            if branch_col and branch_values and all(
                    value.lower() == office for value in branch_values):
                self.last_branch_filter_field = key
                return csv_text

            # The ignored filter response is useful: it exposes the exact
            # underlying/export field caption. Try that exact key next.
            if branch_col and branch_col.lower() not in tried:
                candidates.append(branch_col)

        self.last_branch_filter_field = candidates[-1] if candidates else ""
        return last_csv

    def _pull_rows(self):
        start, end = resolve_dates(self.config)
        base, token, site_id = self.signin()
        try:
            csv_text = self.fetch_csv(base, token, site_id, start, end)
        finally:
            self.signout(base, token)

        rows = to_app_rows(parse_rows(csv_text))
        self.last_remote_rows = len(rows)

        # Never silently put other offices on the Olympia leaderboard. If the
        # workbook ignores a REST filter, use the same Home Branch column as a
        # safety guard. The primary filtering still happens in Tableau.
        branch_values = {
            str(r.get("home_branch") or "").strip()
            for r in rows if str(r.get("home_branch") or "").strip()
        }
        if not branch_values and rows:
            raise TableauError(
                "Tableau returned rows without a Home Branch field, so the Pi "
                "refused to load an unverified all-office result."
            )

        office = TABLEAU_HOME_BRANCH.lower()
        unexpected = {v for v in branch_values if v.lower() != office}
        if unexpected:
            filtered = [
                r for r in rows
                if str(r.get("home_branch") or "").strip().lower() == office
            ]
            if not filtered:
                raise TableauError(
                    "Tableau ignored the Olympia Home Branch filter and no "
                    "Olympia rows could be verified in the returned data."
                )
            self.branch_filter_guard_used = True
            rows = filtered

        return start, end, rows

    def preview(self):
        """Sign in and pull counts only; nothing is written to the database."""
        start, end, rows = self._pull_rows()
        offices = sorted({
            str(r.get("home_branch") or "").strip()
            for r in rows if str(r.get("home_branch") or "").strip()
        })
        return {
            "start": start,
            "end": end,
            "total_rows": self.last_remote_rows or len(rows),
            "selected_rows": len(rows),
            "offices": offices or [TABLEAU_HOME_BRANCH],
            "names": sorted(str(r.get("rep_name")) for r in rows),
        }

    def fetch(self):
        _start, _end, rows = self._pull_rows()
        self.last_total_rows = self.last_remote_rows or len(rows)
        self.last_offices = sorted({
            str(r.get("home_branch") or "").strip()
            for r in rows if str(r.get("home_branch") or "").strip()
        }) or [TABLEAU_HOME_BRANCH]
        return rows
