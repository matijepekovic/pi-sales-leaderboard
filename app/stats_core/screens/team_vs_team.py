class TeamVsTeamScreen:
    key = "team_vs_team"
    label = "Team vs Team"

    def render(self, context, team_pair=None, **_kwargs):
        requested = team_pair if isinstance(team_pair, (list, tuple)) else None
        selected = list(dict.fromkeys(requested or context["settings"].get("team_vs_team_selected") or []))[:2]
        if not selected:
            selected = [team["name"] for team in context["team_defs"][:2]]
        teams = []
        for team_name in selected:
            members = context["grouped"].get(team_name, [])
            definition = context["team_by_name"].get(team_name)
            if not members and not definition:
                continue
            teams.append({
                "summary": context["leaderboard"].aggregate_team(team_name, members, definition),
                "members": context["leaderboard"].sort_rows(members, context["metric"]),
            })
        teams.sort(
            key=lambda item: context["leaderboard"].numeric(item["summary"].get(context["metric"])),
            reverse=True,
        )
        selected_numeric = [
            key for key in context["visible"]
            if context["metric_types"].get(key) in {"number", "percent", "currency"}
        ]
        return {
            "mode": self.key, "mode_label": self.label,
            "metrics": context["visible"], "rows": [], "teams": teams[:2],
            "show_members": True,
            "team_total_metrics": selected_numeric,
            "rep_stat_metrics": selected_numeric,
            "team_rank_metric": context["metric"],
            "team_rank_direction": "desc",
            "snapshot": context["snapshot"],
        }
