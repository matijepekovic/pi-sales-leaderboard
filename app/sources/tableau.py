"""
Tableau connector placeholder.

IMPORTANT ORGANIZATION RULE
---------------------------
Tableau supplies row-level sales metrics and its own source team field, but the
Pi is the authoritative leaderboard organization layer.

The connector should fetch the complete office / branch population needed for
the leaderboard rather than relying on Tableau's team filter. After import:

1. `reps.team` stores Tableau's original team for reference/fallback.
2. `rep_team_assignments` stores persistent Pi overrides.
3. Leaderboards group by the effective Pi team.
4. Moving a rep locally never changes Tableau and is never erased by refresh.
5. Team totals/rates are recalculated from the rep-level raw components.

Only `fetch()` needs to be implemented when Tableau credentials are added.
"""
from .base import LeaderboardSource

class TableauSource(LeaderboardSource):
    def __init__(self, config=None):
        self.config = config or {}

    def fetch(self):
        raise RuntimeError("Tableau source has not been configured yet.")
