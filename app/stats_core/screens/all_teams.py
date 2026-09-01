class AllTeamsScreen:
    key = "all_teams"
    label = "All Teams"

    def render(self, context, **_kwargs):
        teams = []
        for team_name, members in context["grouped"].items():
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
        return {
            "mode": self.key, "mode_label": self.label,
            "metrics": context["visible"], "rows": [], "teams": teams,
            "snapshot": context["snapshot"],
        }
