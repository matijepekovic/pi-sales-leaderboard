"""One Tableau source, described entirely by settings.

Everything the pull needs -- server, site, token name, workbook, sheet, which
export to read, the filters to send, and which column feeds which board stat
-- comes from the saved `source` object. Nothing about the report is compiled
in, so pointing the board at a different report is a settings change rather
than a release.

Connection defaults only tell the Pi how to reach Tableau. The report itself is
never compiled in: no workbook, sheet, filters or mapping exists until the
user saves one from the Data Source card.
"""
from . import tableau_v36_base as _base
from .tableau_mapped import parse_mapped

DEFAULTS = {
    # Connection only. These are what let a fresh Pi sign in and enumerate
    # Tableau content; they do not choose any report or data.
    "server": _base.TABLEAU_SERVER,
    "site": _base.TABLEAU_SITE,
    "pat_name": _base.TABLEAU_PAT_NAME,

    # No report fallback. Until the user saves a tested source, scheduled and
    # manual pulls fail closed and the existing leaderboard rows stay intact.
    "workbook": "",
    "sheet": "",
    "export": "auto",
    "filters": [],
    "date_start_field": "",
    "date_end_field": "",
    "mapping": {},
    "row_filter": {},
}


# Only the connection falls back when a saved value is blank. A blank workbook
# or sheet is intentional and means that no report has been selected.
CONNECTION_REQUIRED = ("server", "site", "pat_name")

EXPORTS = ("auto", "csv", "crosstab")


def config_of(settings):
    """The saved source config, with anything missing filled from DEFAULTS."""
    saved = (settings or {}).get("source")
    config = dict(DEFAULTS)
    if isinstance(saved, dict):
        for key, value in saved.items():
            if key not in config or value is None:
                continue
            if key in CONNECTION_REQUIRED and not str(value).strip():
                continue
            config[key] = value
    config["filters"] = [
        {"field": str(f.get("field") or "").strip(),
         "value": str(f.get("value") or "").strip()}
        for f in (config.get("filters") or [])
        if isinstance(f, dict) and str(f.get("field") or "").strip()
    ]
    config["mapping"] = config.get("mapping") if isinstance(config.get("mapping"), dict) else {}
    config["row_filter"] = (config.get("row_filter")
                            if isinstance(config.get("row_filter"), dict) else {})
    return config


def column_values(csv_text, header):
    """Every distinct non-blank value under one header, and its exact caption.

    Matched loosely so a workbook that renames "USER-Home Branch" to "Home
    Branch" is still recognised -- that rename is the reason the shipped pull
    retried with a second field name.
    """
    reader = _base.csv.DictReader(_base.io.StringIO(csv_text))
    headers = reader.fieldnames or []
    wanted = _base.norm(header)
    caption = ""
    for name in headers:
        if _base.norm(name) == wanted or wanted in _base.norm(name):
            caption = name
            break
    if not caption:
        return "", set()
    values = set()
    for row in reader:
        value = str(row.get(caption) or "").strip()
        if value and value.lower() != "all":
            values.add(value)
    return caption, values


def has_columns(csv_text):
    """True when Tableau actually returned a CSV table."""
    first = str(csv_text or "").lstrip("﻿").strip().splitlines()[:1]
    if not first:
        return False
    headers = next(_base.csv.reader(first), [])
    return len([h for h in headers if str(h).strip()]) >= 2


class ConfiguredTableauSource(_base.TableauSource):
    """The report named in settings, read the way settings says to read it."""

    def __init__(self, config=None, source=None):
        super().__init__(config)
        self.source = source if isinstance(source, dict) else config_of(config)
        self.server = str(self.source["server"]).rstrip("/")
        self.site = str(self.source["site"])
        self.pat_name = str(self.source["pat_name"])
        self.workbook = str(self.source["workbook"]).strip()
        self.sheet = str(self.source["sheet"]).strip()
        self.filters = list(self.source["filters"])
        self.mapping = dict(self.source["mapping"])
        self.row_filter = dict(self.source["row_filter"])
        mode = str(self.source.get("export") or "auto").strip().lower()
        self.export_mode = mode if mode in EXPORTS else "auto"
        self.VIEW_PATH = f"{self.workbook}/sheets/{self.sheet.rsplit('/', 1)[-1]}"
        self.last_notes = {}
        self.last_export = ""
        self.last_filter_fields = []

    # ---------------------------------------------------------- connection

    def _api_base(self):
        version = "3.22"
        status, raw = self._request(f"{self.server}/api/{version}/serverinfo", timeout=20)
        if status == 200:
            try:
                version = _base.json.loads(raw)["serverInfo"]["restApiVersion"]
            except Exception:
                pass
        return f"{self.server}/api/{version}"

    def signin(self):
        secret = self._pat_secret()
        if not secret:
            raise _base.TableauError("Enter the Tableau PAT secret on the Pi first.")
        base = self._api_base()
        status, raw = self._request(
            f"{base}/auth/signin",
            method="POST",
            body={"credentials": {
                "personalAccessTokenName": self.pat_name,
                "personalAccessTokenSecret": secret,
                "site": {"contentUrl": self.site},
            }},
        )
        if status != 200:
            raise _base.TableauError(
                f"Tableau sign-in failed. Check the PAT secret for token "
                f"'{self.pat_name}' on site '{self.site}'."
            )
        try:
            creds = _base.json.loads(raw)["credentials"]
            return base, creds["token"], creds["site"]["id"]
        except Exception as exc:
            raise _base.TableauError(
                "Tableau sign-in returned an unexpected response.") from exc

    # ------------------------------------------------------------- the view

    def _workbook_id(self, base, token, site_id):
        if not self.workbook:
            raise _base.TableauError(
                "No Tableau report is selected. Choose a workbook and sheet "
                "in Data Source, Check The Numbers, then Use This Source.")
        key = _base.urllib.parse.quote(self.workbook, safe="")
        status, raw = self._request(
            f"{base}/sites/{site_id}/workbooks/{key}?key=contentUrl", token=token)
        if status != 200:
            raise _base.TableauError(
                f"Could not find Tableau workbook '{self.workbook}' (HTTP {status}).")
        try:
            workbook_id = str(
                _base.json.loads(raw).get("workbook", {}).get("id") or "").strip()
        except Exception:
            workbook_id = ""
        if not workbook_id:
            raise _base.TableauError(
                f"Tableau workbook '{self.workbook}' returned no id.")
        return workbook_id

    def _view_id(self, base, token, site_id):
        if not self.sheet:
            raise _base.TableauError(
                "No Tableau report is selected. Choose a workbook and sheet "
                "in Data Source, Check The Numbers, then Use This Source.")
        workbook_id = self._workbook_id(base, token, site_id)
        status, raw = self._request(
            f"{base}/sites/{site_id}/workbooks/{workbook_id}/views", token=token)
        if status != 200:
            raise _base.TableauError(f"Could not list views for '{self.workbook}'.")
        try:
            views = self._view_list(_base.json.loads(raw))
        except Exception:
            views = []

        tail = self.sheet.rsplit("/", 1)[-1].lower()
        for view in views:
            content_url = str(view.get("contentUrl") or "").strip().lower()
            url_name = str(view.get("viewUrlName") or "").strip().lower()
            name = str(view.get("name") or "").strip().lower()
            if (url_name == tail or name == tail
                    or content_url.endswith(f"/{tail}")
                    or content_url.endswith(f"/sheets/{tail}")):
                view_id = str(view.get("id") or "").strip()
                if view_id:
                    return view_id

        visible = ", ".join(
            str(v.get("viewUrlName") or v.get("name") or v.get("contentUrl") or "?")
            for v in views[:20]) or "(none visible)"
        raise _base.TableauError(
            f"'{self.workbook}' has no sheet '{self.sheet}'. Sheets: {visible}")

    # ------------------------------------------------------------ the export

    def _query_csv(self, base, token, site_id, view_id, start, end, filters):
        params = {"maxAge": "1"}
        if self.source.get("date_start_field"):
            params[f"vf_{self.source['date_start_field']}"] = start
        if self.source.get("date_end_field"):
            params[f"vf_{self.source['date_end_field']}"] = end
        for item in filters:
            params[f"vf_{item['field']}"] = item["value"]
        query = _base.urllib.parse.urlencode(
            params, quote_via=_base.urllib.parse.quote)
        self.last_filter_fields = [f["field"] for f in filters]
        status, raw = self._request(
            f"{base}/sites/{site_id}/views/{view_id}/data?{query}", token=token)
        if status != 200:
            raise _base.TableauError(
                f"Tableau data request failed (HTTP {status}) for {self.VIEW_PATH}, "
                f"{start} to {end}.")
        return raw.decode("utf-8-sig", errors="replace")

    def _query_crosstab(self, base, token, site_id, view_id, start, end, filters):
        params = {"maxAge": "1"}
        if self.source.get("date_start_field"):
            params[f"vf_{self.source['date_start_field']}"] = start
        if self.source.get("date_end_field"):
            params[f"vf_{self.source['date_end_field']}"] = end
        for item in filters:
            params[f"vf_{item['field']}"] = item["value"]
        query = _base.urllib.parse.urlencode(
            params, quote_via=_base.urllib.parse.quote)
        status, raw = self._request(
            f"{base}/sites/{site_id}/views/{view_id}/crosstab/excel?{query}",
            token=token)
        if status != 200:
            raise _base.TableauError(
                f"Tableau Crosstab download failed (HTTP {status}) for "
                f"{self.VIEW_PATH}. Crosstab comes from a worksheet — if this is "
                "a dashboard, pick the worksheet inside it instead.")
        return raw

    def fetch_csv(self, base, token, site_id, start, end):
        """The view's CSV, with one retry if a filter was ignored.

        Tableau ignores a vf_ filter whose field it does not recognise, which
        is how a renamed caption quietly turns a one-office board into an
        all-office one. When the guarded column comes back with values it
        should not have, retry once using the caption the export itself used.
        """
        view_id = self._view_id(base, token, site_id)
        csv_text = self._query_csv(base, token, site_id, view_id, start, end,
                                   self.filters)

        wanted = str(self.row_filter.get("value") or "").strip()
        if not wanted or not csv_text:
            return csv_text

        for item in self.filters:
            if item["value"].lower() != wanted.lower():
                continue
            caption, values = column_values(csv_text, item["field"])
            others = {v for v in values if v.lower() != wanted.lower()}
            if caption and others and _base.norm(caption) != _base.norm(item["field"]):
                retry = [dict(f) for f in self.filters]
                for candidate in retry:
                    if candidate["field"] == item["field"]:
                        candidate["field"] = caption
                return self._query_csv(base, token, site_id, view_id, start, end,
                                       retry)
        return csv_text

    def read_export(self, base, token, site_id, start, end):
        """(payload, which export) for the configured view.

        Which export is a choice, not a guess. `auto` prefers the view's own
        CSV and falls back to Crosstab, which is right when the CSV is a clean
        summary -- but a view whose CSV stitches worksheets together answers
        the CSV request perfectly well, so under `auto` the Crosstab is never
        reached. `crosstab` is how you say: read the finished summary table
        Tableau builds for Download > Crosstab, and nothing else.
        """
        if self.export_mode == "crosstab":
            view_id = self._view_id(base, token, site_id)
            book = self._query_crosstab(base, token, site_id, view_id, start,
                                        end, self.filters)
            return book, "crosstab", ""

        csv_error = ""
        csv_text = ""
        try:
            csv_text = self.fetch_csv(base, token, site_id, start, end)
        except _base.TableauError as exc:
            if self.export_mode == "csv":
                raise
            csv_error = str(exc)
        if has_columns(csv_text):
            return csv_text, "csv", ""

        if self.export_mode == "csv":
            raise _base.TableauError(
                f"{self.VIEW_PATH} returned an empty view-data export for "
                f"{start} to {end} — no columns at all. Try the Crosstab export "
                "for this sheet, or check the filters being sent.")

        view_id = self._view_id(base, token, site_id)
        book = self._query_crosstab(base, token, site_id, view_id, start, end,
                                    self.filters)
        return book, "crosstab", csv_error

    # -------------------------------------------------------------- the rows

    def _parse(self, payload, how):
        if how == "crosstab":
            from .tableau_crosstab import map_crosstab
            return map_crosstab(payload, self.mapping)
        if self.mapping.get("rep_name"):
            return parse_mapped(payload, self.mapping)
        # No mapping saved: the shipped parser, byte for byte what the board
        # has always used for its own report.
        from .tableau import summary_rows_with_notes
        reps, collapsed = summary_rows_with_notes(payload)
        return reps, {"shape": "shipped",
                      "collapsed": sorted({field for _rep, field in collapsed})}

    def _pull_rows(self):
        start, end = _base.resolve_dates(self.config)
        base, token, site_id = self.signin()
        try:
            payload, how, csv_error = self.read_export(base, token, site_id,
                                                       start, end)
        finally:
            self.signout(base, token)

        self.last_export = how
        reps, notes = self._parse(payload, how)
        self.last_notes = dict(notes or {}, export=how,
                               **({"csv_error": csv_error} if csv_error else {}))
        rows = _base.to_app_rows(reps)
        self.last_remote_rows = len(rows)
        return start, end, self.apply_row_filter(rows)

    def apply_row_filter(self, rows):
        """Keep only the rows the configuration asks for. No rule, no filter."""
        column = str(self.row_filter.get("column") or "").strip()
        wanted = str(self.row_filter.get("value") or "").strip()
        if not column or not wanted:
            return rows

        present = {str(r.get(column) or "").strip() for r in rows}
        present = {v for v in present if v}
        if not present:
            raise _base.TableauError(
                f"That report returned rows with no {column}, so the Pi refused "
                f"to load an unverified result. Clear the row filter in "
                f"settings if this report is not per-{column}.")

        unexpected = {v for v in present if v.lower() != wanted.lower()}
        if not unexpected:
            return rows

        kept = [r for r in rows
                if str(r.get(column) or "").strip().lower() == wanted.lower()]
        if not kept:
            raise _base.TableauError(
                f"That report returned no '{wanted}' rows — it came back with "
                + ", ".join(sorted(unexpected)[:5]))
        self.branch_filter_guard_used = True
        return kept
