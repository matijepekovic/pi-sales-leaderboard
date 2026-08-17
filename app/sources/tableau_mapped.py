"""Pull any Tableau report and map its columns onto the board's stats.

The shipped rep pull understands exactly one report in exactly one shape.
This one understands whichever report you point it at, given a mapping of
"this column feeds that stat" -- so changing report becomes a settings job
rather than a code change.

It overrides _pull_rows outright instead of reusing the base's. The base
resolves its parser from a module-level `parse_rows` that tableau.py owns
and replaces at import; hooking into that would mean two connectors fighting
over one global. Overriding keeps this self-contained and leaves the shipped
rep pull's parsing completely alone.

Two report shapes are handled, chosen automatically:

  long  - Tableau's Measure Names / Measure Values pivot, one row per
          rep-and-measure. This is what the board reads today.
  wide  - one row per rep, one column per measure. This is what the
          Sales Totals & Retention and Net Ranked reports look like.
"""
from . import tableau_v36_base as _base
from .tableau_custom import CustomTableauSource

# Board stat -> the camelCase key to_app_rows() expects. Same set the shipped
# parser fills, so a mapped pull produces rows the rest of the app already
# knows how to render.
STAT_TO_CAMEL = {snake: camel for camel, snake in _base.SCHEMA_MAP.items()}

# Stats that are rates. Tableau hands these back as fractions on every report
# seen so far, while the app works in 0..100.
PERCENT_STATS = {"pitched_rate", "close_rate", "sales_retention"}

MEASURE_NAME_HINTS = ("measurenames", "measure")
MEASURE_VALUE_HINTS = ("measurevalues", "value")

# How far into the export to look for an example value per column.
SAMPLE_ROWS = 40


def detect_shape(headers):
    """'long' if this export pivots measures into rows, else 'wide'."""
    normalized = [_base.norm(h) for h in headers or []]
    has_names = any(any(h == hint for hint in MEASURE_NAME_HINTS) for h in normalized)
    has_values = any(any(h == hint for hint in MEASURE_VALUE_HINTS) for h in normalized)
    return "long" if (has_names and has_values) else "wide"


def describe_report(csv_text):
    """What this export offers to map against.

    In a wide report the mappable things are its column headers. In a long
    one they are the distinct values of Measure Names, because that is where
    the metric names actually live -- the headers are just the pivot's
    scaffolding. The UI needs the same list either way.

    `samples` carries the first real value found behind each name, so the
    person doing the mapping can recognise a column by what is in it rather
    than by trusting its title.
    """
    reader = _base.csv.DictReader(_base.io.StringIO(csv_text))
    headers = reader.fieldnames or []
    shape = detect_shape(headers)
    rows = list(reader)

    samples = {}
    for header in headers:
        for row in rows[:SAMPLE_ROWS]:
            value = str(row.get(header) or "").strip()
            if value:
                samples[header] = value[:40]
                break

    if shape != "long":
        return {"shape": shape, "headers": headers, "choices": list(headers),
                "samples": samples}

    measure_col = _base.find_column(headers, list(MEASURE_NAME_HINTS))
    value_col = _base.find_column(headers, list(MEASURE_VALUE_HINTS))
    labels = []
    for row in rows:
        label = str(row.get(measure_col) or "").strip()
        if not label:
            continue
        if label not in labels:
            labels.append(label)
        if label not in samples:
            value = str(row.get(value_col) or "").strip()
            if value:
                samples[label] = value[:40]

    # A pivot whose Measure Names column came back empty still has to be
    # mappable -- fall back to the headers rather than showing an empty list
    # and leaving no way to match anything.
    return {"shape": shape, "headers": headers,
            "choices": labels or list(headers), "samples": samples}


def suggest_mapping(headers, choices=None):
    """A first guess at which column (or measure) feeds which stat.

    Matched on normalised names, so "Issued Leads Split" finds issued_leads
    and "Sale (Pending) Split" finds pending_split without anyone typing
    anything. Whatever it gets wrong is a dropdown away in the UI.

    rep/branch/team always come from real columns; the metrics come from
    `choices`, which is the headers for a wide report and the measure names
    for a long one.
    """
    guess = {"rep_name": "", "home_branch": "", "team": "", "metrics": {}}
    by_norm = {_base.norm(h): h for h in headers or []}
    taken = set()

    def score(alias, key):
        """How well an alias fits a candidate. None means no fit at all."""
        if key == alias:
            return 0                      # exact -- unbeatable
        if key.startswith(alias):
            return 1 + len(key) - len(alias)
        if alias in key:
            # A later match is usually a qualifier rather than the thing
            # itself: "avggrosssplit" should not win "grosssplit".
            return 100 + key.index(alias) + len(key) - len(alias)
        return None

    def first(*aliases, pool=None, reserve=False):
        candidates = pool if pool is not None else by_norm
        best, best_score = "", None
        for rank, alias in enumerate(aliases):
            for key, header in candidates.items():
                if reserve and header in taken:
                    continue
                s = score(alias, key)
                if s is None:
                    continue
                # Earlier aliases are more specific, so weight by position.
                s += rank * 1000
                if best_score is None or s < best_score:
                    best, best_score = header, s
        if reserve and best:
            taken.add(best)
        return best

    guess["rep_name"] = first("srname", "teamleadsalesrep", "salesrep", "repname", "rep")
    guess["home_branch"] = first("homebranch", "branchnew", "branch", "market", "office")
    guess["team"] = first("srteamleadusertext", "teamlead")

    # Metrics are matched against the choices, which differ from the headers
    # on a long report.
    pool = {_base.norm(c): c for c in (choices if choices is not None else headers) or []}

    # Order matters: the most specific stats claim their column first, so
    # "Avg. Gross Split" cannot be stolen by plain gross_split.
    metrics = {}
    for stat, aliases in (
        ("avg_gross_sale", ("avggrosssplit", "avggrosssale", "avggross")),
        ("avg_net_sale", ("avgnetsplit", "avgnetsale", "avgnet")),
        ("pitched_rate", ("pitchedrate", "pitchrate")),
        ("close_rate", ("closerate",)),
        ("sales_retention", ("salesretention", "retention")),
        ("dpl", ("dplsplit", "dpl")),
        ("issued_leads", ("issuedleadssplit", "issuedleads", "issued")),
        ("pitched_leads", ("pitchedleadssplit", "pitchedleads", "pitched")),
        ("sold_leads", ("soldleadssplit", "soldleads", "sold")),
        ("pending_split", ("salependingsplit", "pendingsplit", "pending")),
        ("gross_split", ("grosssplit", "gross")),
        ("net_split", ("netsplit", "net")),
    ):
        hit = first(*aliases, pool=pool, reserve=True)
        if hit:
            metrics[stat] = hit
    guess["metrics"] = metrics
    return guess


def unmapped_columns(choices, mapping):
    """Whatever the mapping leaves unused, so the UI can say so out loud."""
    used = {mapping.get("rep_name"), mapping.get("home_branch"), mapping.get("team")}
    used |= set((mapping.get("metrics") or {}).values())
    used = {u for u in used if u}
    return [c for c in (choices or []) if c and c not in used]


def _scale_percent(values):
    """True when a rate column is expressed as a fraction rather than 0..100."""
    seen = [v for v in values if v is not None]
    if not seen:
        return False
    return max(abs(v) for v in seen) <= 1.0


def parse_mapped(csv_text, mapping, shape=""):
    """Turn any supported export into the app's rep rows."""
    reader = _base.csv.DictReader(_base.io.StringIO(csv_text))
    headers = reader.fieldnames or []
    rows = list(reader)
    shape = shape or detect_shape(headers)

    rep_col = mapping.get("rep_name") or ""
    if not rep_col or rep_col not in headers:
        raise _base.TableauError(
            "No column is mapped to the rep name. Columns available: "
            + (", ".join(headers) if headers else "none")
        )

    branch_col = mapping.get("home_branch") or ""
    team_col = mapping.get("team") or ""
    metrics = {k: v for k, v in (mapping.get("metrics") or {}).items() if v}

    # Crosstab exports blank a repeated dimension; carry the last value down
    # so every rep keeps its branch.
    last_branch = ""
    collected = {}
    order = []

    for row in rows:
        name = str(row.get(rep_col) or "").strip()
        if not name or name.lower() in {"grand total", "total", "all"}:
            continue

        branch = str(row.get(branch_col) or "").strip() if branch_col else ""
        if branch:
            last_branch = branch
        else:
            branch = last_branch

        if name not in collected:
            collected[name] = {
                "name": name,
                "home_branch": branch,
                "team": str(row.get(team_col) or "").strip() if team_col else "",
                "raw": {stat: [] for stat in metrics},
            }
            order.append(name)

        if shape == "long":
            measure_col = _base.find_column(headers, list(MEASURE_NAME_HINTS))
            value_col = _base.find_column(headers, list(MEASURE_VALUE_HINTS))
            label = str(row.get(measure_col) or "").strip()
            value = _base.clean_number(row.get(value_col))
            if value is None:
                continue
            for stat, column in metrics.items():
                if _base.norm(column) == _base.norm(label):
                    collected[name]["raw"][stat].append(value)
        else:
            for stat, column in metrics.items():
                value = _base.clean_number(row.get(column))
                if value is not None:
                    collected[name]["raw"][stat].append(value)

    if not collected:
        raise _base.TableauError(
            f"No rows had a value in '{rep_col}'. Is that the right column?"
        )

    # Decide the rate scale once per stat, from everything that came back,
    # rather than guessing per row.
    scale = {}
    for stat in metrics:
        if stat in PERCENT_STATS:
            pooled = [v for rec in collected.values() for v in rec["raw"][stat]]
            scale[stat] = 100.0 if _scale_percent(pooled) else 1.0
        else:
            scale[stat] = 1.0

    reps = []
    for name in order:
        rec = collected[name]
        out = {
            "name": rec["name"],
            "home_branch": rec["home_branch"],
            "team": rec["team"],
        }
        for stat, values in rec["raw"].items():
            camel = STAT_TO_CAMEL.get(stat)
            if not camel or not values:
                continue
            # Several rows for one rep means a split across months; rates are
            # already finished figures, so take one rather than summing.
            total = max(values) if stat in PERCENT_STATS else sum(values)
            out[camel] = total * scale[stat]
        reps.append(out)

    return reps, {"shape": shape, "scaled": sorted(s for s in scale if scale[s] != 1.0)}


class MappedTableauSource(CustomTableauSource):
    """The chosen report, read through the chosen column mapping."""

    def __init__(self, config=None, workbook="", sheet="", mapping=None):
        super().__init__(config, workbook, sheet)
        self.mapping = mapping or {}
        self.last_notes = {}

    def _pull_rows(self):
        start, end = _base.resolve_dates(self.config)
        base, token, site_id = self.signin()
        try:
            csv_text = self.fetch_csv(base, token, site_id, start, end)
        finally:
            self.signout(base, token)

        reps, notes = parse_mapped(csv_text, self.mapping)
        self.last_notes = notes
        rows = _base.to_app_rows(reps)
        self.last_remote_rows = len(rows)

        # Same protection the shipped pull has: never put another office on
        # the Olympia board. Only possible when a branch column is mapped --
        # the preview says so when it is not.
        if self.mapping.get("home_branch"):
            office = _base.TABLEAU_HOME_BRANCH.lower()
            values = {
                str(r.get("home_branch") or "").strip()
                for r in rows if str(r.get("home_branch") or "").strip()
            }
            unexpected = {v for v in values if v.lower() != office}
            if unexpected:
                filtered = [
                    r for r in rows
                    if str(r.get("home_branch") or "").strip().lower() == office
                ]
                if not filtered:
                    raise _base.TableauError(
                        "That report returned no Olympia rows — it came back with "
                        + ", ".join(sorted(unexpected)[:5])
                    )
                self.branch_filter_guard_used = True
                rows = filtered

        return start, end, rows
