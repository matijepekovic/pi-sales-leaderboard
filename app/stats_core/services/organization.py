"""Team/leader/assignment ownership."""
from __future__ import annotations

import os
from pathlib import Path

from stats_core.errors import ValidationError
from stats_core.services.settings import split_active_mode


class OrganizationService:
    def __init__(self, repos, team_logo_dir: Path):
        self.repos = repos
        self.team_logo_dir = Path(team_logo_dir)

    def definitions_for_api(self):
        teams = self.repos.organization.definitions()
        reps = self.repos.reps.list()
        effective_members = {}
        for rep in reps:
            team_id = rep.get("team_id")
            if team_id:
                effective_members.setdefault(int(team_id), []).append(rep.get("rep_key"))
        organization_version = int(self.repos.meta.get("organization_version", "0") or 0)
        for team in teams:
            team_id = int(team["team_id"])
            team["member_rep_keys"] = effective_members.get(team_id, [])
            team["logo_url"] = (
                f"/api/teams/{team_id}/logo?v={organization_version}"
                if team.get("logo_path") else None
            )
        return teams

    def leader_candidates(self):
        candidates = {}
        for rep in self.repos.reps.list():
            source_lead = str(rep.get("team_lead") or "").strip()
            if source_lead:
                candidates.setdefault(
                    source_lead.lower(),
                    {"name": source_lead, "source": "Source Team Lead"},
                )
            title = str(rep.get("title") or "").strip()
            if any(token in title.lower() for token in ("manager", "smit", "manager in training")):
                name = str(rep.get("rep_name") or "").strip()
                if name:
                    candidates.setdefault(
                        name.lower(),
                        {"name": name, "source": title or "Source"},
                    )
        for team in self.repos.organization.definitions():
            leader = team.get("leader")
            if leader and leader.get("lead_name"):
                name = str(leader["lead_name"]).strip()
                candidates.setdefault(name.lower(), {"name": name, "source": leader.get("lead_role") or "Saved Leader"})
        return sorted(candidates.values(), key=lambda item: item["name"].lower())

    def rep_summaries(self):
        rows = []
        for rep in sorted(
            self.repos.reps.list(),
            key=lambda item: str(item.get("rep_name") or "").lower(),
        ):
            source_team = rep.get("source_team") or "Unassigned"
            rows.append({
                "rep_key": rep.get("rep_key"),
                "rep_name": rep.get("rep_name"),
                "source_team": source_team,
                # Kept only for older clients reading /api/config. New Settings
                # code consumes source_team from /api/organization.
                "tableau_team": source_team,
                "effective_team": rep.get("team") or "Unassigned",
                "effective_team_id": rep.get("team_id"),
                "assigned_team_id": rep.get("assigned_team_id"),
                "local_team_override": bool(rep.get("local_team_override")),
            })
        return rows

    def create(self, name):
        return self.repos.organization.create(name)

    def rename(self, team_id, name):
        return self.repos.organization.rename(team_id, name)

    def set_leader(self, team_id, name, role):
        return self.repos.organization.set_leader(team_id, name, role)

    def delete_leader(self, lead_id):
        return self.repos.organization.delete_leader(lead_id)

    def assign_reps(self, assignments):
        if not isinstance(assignments, list):
            raise ValidationError("assignments must be a list")
        return self.repos.organization.assign_reps(assignments)

    def save_builder(self, incoming):
        return self.repos.organization.save_builder(
            incoming.get("team_id"), incoming.get("name"), incoming.get("leader_name"),
            incoming.get("leader_role", "Sales Manager"), incoming.get("member_rep_keys", []),
        )

    def save_logo(self, team_id, upload):
        if not upload or not upload.filename:
            raise ValidationError("Choose a logo file.")
        ext = Path(upload.filename).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            raise ValidationError("Logo must be PNG, JPG, or WEBP.")
        upload.stream.seek(0, os.SEEK_END)
        size = upload.stream.tell()
        upload.stream.seek(0)
        if size > 5 * 1024 * 1024:
            raise ValidationError("Logo must be under 5 MB.")
        self.team_logo_dir.mkdir(parents=True, exist_ok=True)
        for old in self.team_logo_dir.glob(f"team-{team_id}.*"):
            try: old.unlink()
            except Exception: pass
        path = self.team_logo_dir / f"team-{team_id}{ext}"
        upload.save(path)
        self.repos.organization.set_logo(team_id, str(path))
        return f"/api/teams/{team_id}/logo?v={int(self.repos.meta.get('organization_version','0') or 0)}"

    def delete_logo(self, team_id):
        team = next((item for item in self.repos.organization.definitions(include_inactive=True) if int(item["team_id"]) == int(team_id)), None)
        if team and team.get("logo_path"):
            try: Path(team["logo_path"]).unlink(missing_ok=True)
            except Exception: pass
        self.repos.organization.set_logo(team_id, None)

    def logo_path(self, team_id):
        team = next((item for item in self.repos.organization.definitions(include_inactive=True) if int(item["team_id"]) == int(team_id)), None)
        if not team or not team.get("logo_path"):
            return None
        path = Path(team["logo_path"])
        return path if path.exists() else None

    def delete_team(self, team_id, reassignments):
        result = self.repos.organization.delete(team_id, reassignments)
        if result.get("logo_path"):
            try: Path(result["logo_path"]).unlink(missing_ok=True)
            except Exception: pass
        current = self.repos.settings.get()
        deleted_name = result["name"]
        current["team_vs_team_selected"] = [name for name in (current.get("team_vs_team_selected") or []) if str(name).lower() != deleted_name.lower()][:2]
        remaining = self.repos.organization.definitions()
        by_id = {int(team["team_id"]): team["name"] for team in remaining}
        destinations = [by_id[team_id] for team_id in result.get("destination_team_ids", []) if team_id in by_id]
        for candidate in destinations + [team["name"] for team in remaining]:
            if len(current["team_vs_team_selected"]) >= 2: break
            if candidate not in current["team_vs_team_selected"]: current["team_vs_team_selected"].append(candidate)
        if str(current.get("per_team_selected") or "").lower() == deleted_name.lower():
            current["per_team_selected"] = destinations[0] if destinations else (remaining[0]["name"] if remaining else "")
        mode, team = split_active_mode(current.get("active_mode", ""))
        if mode == "per_team" and str(team).lower() == deleted_name.lower():
            current["active_mode"] = f"per_team::{current['per_team_selected']}" if current.get("per_team_selected") else "whole_office"
        self.repos.settings.save(current)
        self.repos.meta.bump("settings_version")
        return result
