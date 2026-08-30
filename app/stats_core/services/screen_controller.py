"""Where the TV is currently pointed.

The macro pad and keyboard do not change settings -- they steer the board for a
while and then let it drift back to whatever Settings says. That temporary
steer used to live in a closure inside the display's own JavaScript, which made
it private to one browser tab: a second screen never saw it, a reload lost it,
and the screen list had to be duplicated in the page to walk it.

It lives here now. Actions arrive by name, the resulting view is returned, and
an idle period returns the board to the configured view on its own.
"""
from __future__ import annotations

import threading
import time

INACTIVITY_SECONDS = 5 * 60
NUMERIC_TYPES = ("number", "percent", "currency")


def parsed_mode(view):
    """per_team::Undisputed is the per_team screen showing one team."""
    view = str(view or "")
    return "per_team" if view.startswith("per_team::") else view


class ScreenController:
    """The temporary view override, and the actions that move it."""

    def __init__(self, repos, screens, metric_defs, inactivity_seconds=INACTIVITY_SECONDS):
        self.repos = repos
        self.screens = screens
        self.metric_defs = tuple(metric_defs)
        self.inactivity_seconds = float(inactivity_seconds)
        self._lock = threading.Lock()
        self._override = None
        self._version = 0

    # -- what Settings says, when nothing is steering ----------------------

    def configured_view(self, settings=None):
        settings = self.repos.settings.get() if settings is None else settings
        active = str(settings.get("active_mode") or "whole_office")
        if active == "per_team":
            team = str(settings.get("per_team_selected") or "").strip()
            if team:
                return f"per_team::{team}"
        return active

    def cycle(self, settings=None):
        """The views previous/next walks: the chosen subset, or everything."""
        settings = self.repos.settings.get() if settings is None else settings
        available = self.screens.cycle_views()
        saved = settings.get("keyboard_cycle_views")
        if not isinstance(saved, list) or not saved:
            return list(available)
        chosen = [str(v) for v in saved if str(v) in available]
        return chosen or list(available[:1])

    def team_names(self):
        names = []
        for team in self.screens.organization.definitions_for_api():
            name = str(team.get("name") or "").strip()
            if name:
                names.append(name)
        return names

    def pairs(self):
        names = self.team_names()
        return [
            [names[i], names[j]]
            for i in range(len(names))
            for j in range(i + 1, len(names))
        ]

    @staticmethod
    def _same_pair(a, b):
        if not isinstance(a, list) or not isinstance(b, list):
            return False
        if len(a) != 2 or len(b) != 2:
            return False
        left = [str(x).strip().lower() for x in a]
        right = [str(x).strip().lower() for x in b]
        return left == right or left == right[::-1]

    def sortable_metrics(self, mode, settings=None):
        settings = self.repos.settings.get() if settings is None else settings
        types = {key: typ for key, _label, typ in self.metric_defs}
        visible = (settings.get("visible_metrics") or {}).get(mode) or []
        return [
            key for key in visible
            if key != "rank" and types.get(key) in NUMERIC_TYPES
        ]

    # -- the override -------------------------------------------------------

    def _expired(self, state, now):
        return state is not None and now >= state["expires_at"]

    def _ensure(self, settings, now):
        """The live override, seeded from Settings the first time it is needed."""
        state = self._override
        if self._expired(state, now):
            state = self._override = None
        if state is not None:
            return state

        state = {
            "view": self.configured_view(settings),
            "pair": None,
            "sort_by_mode": {},
            "expires_at": now + self.inactivity_seconds,
        }
        selected = [
            str(name) for name in (settings.get("team_vs_team_selected") or [])
            if str(name).strip()
        ][:2]
        if len(selected) == 2:
            state["pair"] = selected
        self._override = state
        return state

    def _ensure_pair(self, state):
        all_pairs = self.pairs()
        if not all_pairs:
            state["pair"] = None
            return None
        found = next(
            (pair for pair in all_pairs if self._same_pair(pair, state["pair"])),
            None,
        )
        state["pair"] = found or all_pairs[0]
        return state["pair"]

    def _move_view(self, state, delta, settings):
        views = self.cycle(settings)
        if not views:
            return False
        if state["view"] in views:
            index = (views.index(state["view"]) + delta) % len(views)
            state["view"] = views[index]
        else:
            state["view"] = views[-1] if delta < 0 else views[0]
        if parsed_mode(state["view"]) == "team_vs_team":
            self._ensure_pair(state)
        return True

    def _move_pair(self, state, delta):
        if parsed_mode(state["view"]) != "team_vs_team":
            return False
        all_pairs = self.pairs()
        if not all_pairs:
            return False
        index = next(
            (i for i, pair in enumerate(all_pairs) if self._same_pair(pair, state["pair"])),
            None,
        )
        index = 0 if index is None else (index + delta) % len(all_pairs)
        state["pair"] = all_pairs[index]
        return True

    def _move_sort(self, state, delta, settings):
        mode = parsed_mode(state["view"])
        metrics = self.sortable_metrics(mode, settings)
        if not metrics:
            return False
        remote = str((settings.get("sort_metric") or {}).get(mode) or "")
        current = str(state["sort_by_mode"].get(mode) or remote)
        index = metrics.index(current) if current in metrics else None
        index = 0 if index is None else (index + delta) % len(metrics)
        state["sort_by_mode"][mode] = metrics[index]
        return True

    # -- the public surface -------------------------------------------------

    def dispatch(self, action, settings=None, now=None):
        """Apply a named action. Returns the resulting state; `changed` says
        whether anything actually moved."""
        action = str(action or "")
        settings = self.repos.settings.get() if settings is None else settings
        now = time.monotonic() if now is None else float(now)

        with self._lock:
            state = self._ensure(settings, now)
            if action == "previous":
                changed = self._move_view(state, -1, settings)
            elif action == "next":
                changed = self._move_view(state, 1, settings)
            elif action == "pair":
                changed = self._move_pair(state, 1)
            elif action in ("sort_prev", "sort_next"):
                changed = self._move_sort(state, -1 if action == "sort_prev" else 1, settings)
            else:
                raise KeyError(action)

            if changed:
                state["expires_at"] = now + self.inactivity_seconds
                self._version += 1
            return self._state(settings, now, changed=changed)

    def release(self, settings=None, now=None):
        """Drop the override immediately and go back to the configured view."""
        settings = self.repos.settings.get() if settings is None else settings
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            if self._override is not None:
                self._override = None
                self._version += 1
            return self._state(settings, now, changed=True)

    def state(self, settings=None, now=None):
        settings = self.repos.settings.get() if settings is None else settings
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            if self._expired(self._override, now):
                self._override = None
                self._version += 1
            return self._state(settings, now, changed=False)

    def _state(self, settings, now, changed):
        """Caller holds the lock."""
        state = self._override
        if state is None:
            return {
                "active": False,
                "changed": changed,
                "version": self._version,
                "view": self.configured_view(settings),
                "pair": None,
                "sort_metric": None,
                "expires_in": 0,
            }
        mode = parsed_mode(state["view"])
        pair = state["pair"] if mode == "team_vs_team" else None
        return {
            "active": True,
            "changed": changed,
            "version": self._version,
            "view": state["view"],
            "pair": list(pair) if pair else None,
            "sort_metric": state["sort_by_mode"].get(mode),
            "expires_in": max(0, int(round(state["expires_at"] - now))),
        }

    def render_arguments(self, settings=None, now=None):
        """What /api/leaderboard should draw when the request names nothing."""
        current = self.state(settings=settings, now=now)
        if not current["active"]:
            return None
        return {
            "mode": current["view"],
            "sort_metric": current["sort_metric"],
            "team_pair": current["pair"],
        }
