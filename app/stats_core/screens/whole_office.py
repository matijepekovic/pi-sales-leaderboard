class WholeOfficeScreen:
    key = "whole_office"
    label = "Whole Office"

    def render(self, context, **_kwargs):
        return {
            "mode": self.key,
            "mode_label": self.label,
            "metrics": context["visible"],
            "rows": context["leaderboard"].sort_rows(context["rows"], context["metric"]),
            "teams": [],
            "office_summary": context["leaderboard"].aggregate_team("WHOLE OFFICE", context["rows"], None),
            "snapshot": context["snapshot"],
        }
