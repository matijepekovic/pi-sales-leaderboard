"""
Tableau connector.

ORGANIZATION RULE
-----------------
Tableau supplies row-level sales metrics. The Pi is the authoritative
leaderboard organization layer:

1. `reps.team` stores Tableau's original team for reference/fallback.
2. `rep_team_assignments` stores persistent Pi overrides.
3. Leaderboards group by the effective Pi team.
4. Moving a rep locally never changes Tableau and is never erased by refresh.

SELECTION RULE
--------------
The pull deliberately fetches the WHOLE population the view exposes, then
filters locally:

    keep rep  <=>  (office matches OR name is force-included)
                   AND name is not excluded

Pre-filtering the query by office would make "always include this person no
matter which office they sit in" impossible, so office is applied here, not
in Tableau. Only the date window is pushed to Tableau, because rows outside
the view's window cannot be recovered locally.

COUNTING RULES (verified against the customer's own Tableau report)
-------------------------------------------------------------------
The export is lead-level and long-format (Measure Names / Measure Values):

* A lead sold with N products appears as N job rows, each repeating the
  lead's split value. Counting measures (issued/pitched/sold) must therefore
  be taken ONCE PER LEAD, or a two-product sale counts as 1.0 instead of 0.5.
* Dollar measures DO sum across job rows (each product carries its own money).
* Tableau emits a per-rep "All" roll-up row; it must be skipped or every
  number doubles.
"""
import csv
import io
import re
from datetime import date

import urllib.parse
import urllib.request
import json

from .base import LeaderboardSource

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
# (alias, field) pairs, longest alias first so specific names win
ALIAS_INDEX = sorted(
    ((a, f) for f, aliases in FIELD_ALIASES.items() for a in aliases),
    key=lambda p: -len(p[0]))

REP_ALIASES = ["srname", "rep", "repname", "salesrep", "salesperson",
               "employee", "assignedrep"]
BRANCH_ALIASES = ["branchnew", "userhomebranch", "homebranch", "branch",
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

# camelCase (parser) -> the app's snake_case rep schema in sources/base.py
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


def derive(r):
    """Fill MISSING computed columns. Values from Tableau are never overwritten."""
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
    """
    Parse a Tableau view-data CSV into camelCase rep dicts.

    Handles both the long format (Measure Names / Measure Values, which is
    what this workbook emits) and a plain wide format.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = reader.fieldnames or []
    hmap = {h: norm(h) for h in headers}

    def col_for(aliases):
        return next((h for h, n in hmap.items() if n in aliases), None)

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

    # per rep: counts keyed by lead (deduped), everything else accumulated
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
            continue                      # per-rep roll-up row

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
                # one value per lead, no matter how many job rows repeat it
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
            if isinstance(agg, dict):                 # per-lead counts
                rec[field] = sum(agg.values())
            else:
                total, count = agg
                rec[field] = (total / count) if field in MEAN_FIELDS and count else total
        rec.update(meta[name])
        reps.append(derive(rec))
    return reps


def to_app_rows(reps):
    """camelCase parser dicts -> the app's rep schema (sources/base.py)."""
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


# ---------------------------------------------------------------- selection

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
    """Current month unless a custom range is set and complete."""
    if str(settings.get("data_date_mode") or "current_month") == "custom":
        start = str(settings.get("data_date_start") or "").strip()
        end = str(settings.get("data_date_end") or "").strip()
        if start and end:
            return start, end
    return month_range(today)


def _names(values):
    return {str(v).strip().lower() for v in (values or []) if str(v).strip()}


def apply_selection(rows, settings):
    """
    keep rep <=> (office matches OR force-included) AND not excluded

    Office "" means every office. Exclusion always wins over inclusion.
    """
    office = str(settings.get("data_office") or "").strip().lower()
    include = _names(settings.get("data_include_people"))
    exclude = _names(settings.get("data_exclude_people"))

    kept = []
    for row in rows:
        name = str(row.get("rep_name") or "").strip().lower()
        if name in exclude:
            continue
        if office and str(row.get("home_branch") or "").strip().lower() != office:
            if name not in include:
                continue
        kept.append(row)
    return kept


# ---------------------------------------------------------------- Tableau IO

class TableauError(RuntimeError):
    pass


class TableauSource(LeaderboardSource):
    def __init__(self, config=None):
        self.config = config or {}
        self.last_offices = []
        self.last_total_rows = 0

    # -- low level ---------------------------------------------------
    def _cfg(self, key, default=""):
        return str(self.config.get(key) or default).strip()

    def _request(self, url, method="GET", token=None, body=None, timeout=60):
        headers = {"Accept": "application/json",
                   "User-Agent": "pi-tableau-sales-leaderboard"}
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

    def _api_base(self, server):
        version = "3.22"
        status, raw = self._request(f"{server}/api/{version}/serverinfo", timeout=20)
        if status == 200:
            try:
                version = json.loads(raw)["serverInfo"]["restApiVersion"]
            except Exception:
                pass
        return f"{server}/api/{version}"

    def signin(self):
        server = self._cfg("tableau_server").rstrip("/")
        site = self._cfg("tableau_site")
        pat_name = self._cfg("tableau_pat_name")
        pat_secret = self._cfg("tableau_pat_secret")
        if not (server and pat_name and pat_secret):
            raise TableauError("Tableau server, token name and token secret are required.")

        base = self._api_base(server)
        status, raw = self._request(
            f"{base}/auth/signin", method="POST",
            body={"credentials": {
                "personalAccessTokenName": pat_name,
                "personalAccessTokenSecret": pat_secret,
                "site": {"contentUrl": site},
            }},
        )
        if status != 200:
            raise TableauError(
                "Tableau sign-in failed. Check the token name, token secret and site."
            )
        creds = json.loads(raw)["credentials"]
        return base, creds["token"], creds["site"]["id"]

    def signout(self, base, token):
        try:
            self._request(f"{base}/auth/signout", method="POST", token=token)
        except Exception:
            pass

    def fetch_csv(self, base, token, site_id, start, end):
        """Locate the saved custom view, then pull its underlying view data."""
        view_name = self._cfg("tableau_view")
        status, raw = self._request(
            f"{base}/sites/{site_id}/customviews?pageSize=1000", token=token)
        if status != 200:
            raise TableauError("Could not list Tableau custom views.")
        views = json.loads(raw).get("customViews", {}).get("customView", [])
        cv = next((c for c in views
                   if str(c.get("name", "")).strip().lower() == view_name.lower()), None)
        if not cv:
            names = ", ".join(str(c.get("name")) for c in views[:15]) or "(none visible)"
            raise TableauError(f"Custom view '{view_name}' not found. Visible: {names}")
        view_id = (cv.get("view") or {}).get("id")
        if not view_id:
            raise TableauError("That custom view has no underlying view id.")

        params = {"maxAge": "1"}
        p_start = self._cfg("data_date_param_start", "Start")
        p_end = self._cfg("data_date_param_end", "End")
        if p_start and start:
            params[f"vf_{p_start}"] = start
        if p_end and end:
            params[f"vf_{p_end}"] = end
        query = urllib.parse.urlencode(params)

        # Underlying view = the whole population, which local selection needs.
        status, raw = self._request(
            f"{base}/sites/{site_id}/views/{view_id}/data?{query}", token=token)
        if status != 200:
            raise TableauError(f"Tableau data request failed (HTTP {status}).")
        return raw.decode("utf-8-sig", errors="replace")

    # -- public ------------------------------------------------------
    def preview(self):
        """Sign in and pull, but return counts only. Nothing is written."""
        start, end = resolve_dates(self.config)
        base, token, site_id = self.signin()
        try:
            csv_text = self.fetch_csv(base, token, site_id, start, end)
        finally:
            self.signout(base, token)
        rows = to_app_rows(parse_rows(csv_text))
        offices = sorted({str(r.get("home_branch") or "").strip()
                          for r in rows if str(r.get("home_branch") or "").strip()})
        selected = apply_selection(rows, self.config)
        return {
            "start": start, "end": end,
            "total_rows": len(rows),
            "selected_rows": len(selected),
            "offices": offices,
            "names": sorted(str(r.get("rep_name")) for r in rows),
        }

    def fetch(self):
        start, end = resolve_dates(self.config)
        base, token, site_id = self.signin()
        try:
            csv_text = self.fetch_csv(base, token, site_id, start, end)
        finally:
            self.signout(base, token)
        rows = to_app_rows(parse_rows(csv_text))
        self.last_total_rows = len(rows)
        self.last_offices = sorted({str(r.get("home_branch") or "").strip()
                                    for r in rows if str(r.get("home_branch") or "").strip()})
        return apply_selection(rows, self.config)
