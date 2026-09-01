class PerTeamScreen:
    key = "per_team"
    label = "Per Team"

    def render(self, context, **_kwargs):
        selected_team = context["parsed_team"] or context["settings"].get("per_team_selected") or ""
        if not selected_team and context["team_defs"]:
            selected_team = context["team_defs"][0]["name"]
        members = context["grouped"].get(selected_team, [])
        definition = context["team_by_name"].get(selected_team)
        return {
            "mode": self.key,
            "mode_label": f"{self.label} — {selected_team}" if selected_team else self.label,
            "metrics": context["visible"],
            "rows": context["leaderboard"].sort_rows(members, context["metric"]),
            "teams": [],
            "selected_team": selected_team,
            "team_summary": (
                context["leaderboard"].aggregate_team(selected_team, members, definition)
                if selected_team else None
            ),
            "snapshot": context["snapshot"],
        }
