from __future__ import annotations

from stats_core.storage import sqlite as database


class OrganizationRepository:
    def __init__(self, meta_repo):
        self.meta = meta_repo

    @staticmethod
    def ensure_source_team_in_connection(con, name):
        name = str(name or "").strip()
        if not name or name.lower() == "unassigned":
            return None
        con.execute(
            "INSERT INTO teams(name,active) VALUES(?,1) "
            "ON CONFLICT(name) DO UPDATE SET active=1",
            (name,),
        )
        row = con.execute(
            "SELECT team_id FROM teams WHERE name=? COLLATE NOCASE",
            (name,),
        ).fetchone()
        return int(row["team_id"]) if row else None

    def list_team_names(self):
        return [
            {
                "team_id": team["team_id"],
                "team": team["name"],
                "reps": team["rep_count"],
                "leads": team["leads"],
            }
            for team in self.definitions()
        ]

    def definitions(self, include_inactive=False):
        where = "" if include_inactive else "WHERE t.active=1"
        with database.connect() as con:
            teams = [
                dict(row)
                for row in con.execute(
                    f"SELECT t.team_id,t.name,t.logo_path,t.active,t.created_at FROM teams t {where} "
                    "ORDER BY t.name COLLATE NOCASE"
                ).fetchall()
            ]
            leads = [
                dict(row)
                for row in con.execute(
                    "SELECT lead_id,team_id,lead_name,lead_role FROM team_leads "
                    "ORDER BY lead_name COLLATE NOCASE"
                ).fetchall()
            ]
            assignments = {
                row["rep_key"]: int(row["team_id"])
                for row in con.execute(
                    "SELECT rep_key,team_id FROM rep_team_assignments"
                ).fetchall()
            }
            source_reps = [
                dict(row)
                for row in con.execute("SELECT rep_key,team FROM reps").fetchall()
            ]

        leads_by_team = {}
        for lead in leads:
            leads_by_team.setdefault(int(lead["team_id"]), []).append(lead)

        local_counts = {}
        for team_id in assignments.values():
            local_counts[team_id] = local_counts.get(team_id, 0) + 1

        team_id_by_name = {
            team["name"].lower(): int(team["team_id"])
            for team in teams
        }
        effective_counts = {}
        for rep in source_reps:
            team_id = assignments.get(rep["rep_key"])
            if not team_id:
                team_id = team_id_by_name.get(
                    str(rep.get("team") or "").strip().lower()
                )
            if team_id:
                effective_counts[team_id] = effective_counts.get(team_id, 0) + 1

        for team in teams:
            team_id = int(team["team_id"])
            team_leads = leads_by_team.get(team_id, [])
            team["leader"] = team_leads[0] if team_leads else None
            team["leads"] = team_leads[:1]
            team["assigned_rep_count"] = local_counts.get(team_id, 0)
            team["rep_count"] = effective_counts.get(team_id, 0)
        return teams

    def apply_overlay(self, rows):
        rows = list(rows or [])
        with database.connect() as con:
            assignments = {
                row["rep_key"]: int(row["team_id"])
                for row in con.execute(
                    "SELECT rep_key,team_id FROM rep_team_assignments"
                ).fetchall()
            }
            teams = {
                int(row["team_id"]): row["name"]
                for row in con.execute(
                    "SELECT team_id,name FROM teams WHERE active=1"
                ).fetchall()
            }
        team_ids_by_name = {
            name.lower(): team_id for team_id, name in teams.items()
        }

        for row in rows:
            tableau_team = (
                str(row.get("team") or "Unassigned").strip() or "Unassigned"
            )
            assigned_team_id = assignments.get(row.get("rep_key"))
            assigned_team_name = (
                teams.get(assigned_team_id) if assigned_team_id else None
            )

            if assigned_team_name:
                effective_team = assigned_team_name
                effective_team_id = assigned_team_id
                local_override = True
            else:
                effective_team = tableau_team
                effective_team_id = team_ids_by_name.get(tableau_team.lower())
                local_override = False

            row["tableau_team"] = tableau_team
            row["team"] = effective_team
            row["team_id"] = effective_team_id
            row["assigned_team_id"] = assigned_team_id
            row["team_override"] = assigned_team_name or ""
            row["local_team_override"] = local_override
        return rows

    def save_builder(self, team_id, name, leader_name, leader_role, member_rep_keys):
        name = str(name or "").strip()
        if not name:
            raise ValueError("Team name is required.")

        leader_name = str(leader_name or "").strip()
        leader_role = str(leader_role or "Sales Manager").strip() or "Sales Manager"
        desired_members = {
            str(value).strip()
            for value in (member_rep_keys or [])
            if str(value).strip()
        }

        with database.connect() as con:
            if team_id:
                team_id = int(team_id)
                con.execute(
                    "UPDATE teams SET name=?,active=1 WHERE team_id=?",
                    (name, team_id),
                )
            else:
                con.execute(
                    "INSERT INTO teams(name,active) VALUES(?,1)",
                    (name,),
                )
                team_id = int(
                    con.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
                )

            con.execute("DELETE FROM team_leads WHERE team_id=?", (team_id,))
            if leader_name:
                con.execute(
                    "INSERT INTO team_leads(team_id,lead_name,lead_role) VALUES(?,?,?)",
                    (team_id, leader_name, leader_role),
                )

            current = {
                row["rep_key"]
                for row in con.execute(
                    "SELECT rep_key FROM rep_team_assignments WHERE team_id=?",
                    (team_id,),
                ).fetchall()
            }
            for rep_key in current - desired_members:
                con.execute(
                    "DELETE FROM rep_team_assignments WHERE rep_key=? AND team_id=?",
                    (rep_key, team_id),
                )
            for rep_key in desired_members:
                con.execute(
                    "INSERT INTO rep_team_assignments(rep_key,team_id) VALUES(?,?) "
                    "ON CONFLICT(rep_key) DO UPDATE SET team_id=excluded.team_id",
                    (rep_key, team_id),
                )

        self.meta.bump("organization_version")
        return team_id

    def create(self, name):
        name = str(name or "").strip()
        if not name:
            raise ValueError("Team name is required.")
        with database.connect() as con:
            team_id = self.ensure_source_team_in_connection(con, name)
        self.meta.bump("organization_version")
        return team_id

    def rename(self, team_id, name):
        name = str(name or "").strip()
        if not name:
            raise ValueError("Team name is required.")
        with database.connect() as con:
            con.execute(
                "UPDATE teams SET name=?, active=1 WHERE team_id=?",
                (name, int(team_id)),
            )
        self.meta.bump("organization_version")

    def delete(self, team_id, reassignments=None):
        team_id = int(team_id)
        reassignments = reassignments or []
        requested = {
            str(item.get("rep_key") or "").strip(): int(item.get("team_id"))
            for item in reassignments
            if str(item.get("rep_key") or "").strip()
            and item.get("team_id") not in (None, "", 0, "0")
        }

        with database.connect() as con:
            team = con.execute(
                "SELECT team_id,name,logo_path FROM teams WHERE team_id=? AND active=1",
                (team_id,),
            ).fetchone()
            if not team:
                raise ValueError("Team not found.")

            team_name = str(team["name"])
            logo_path = team["logo_path"]
            active_destinations = {
                int(row["team_id"]): row["name"]
                for row in con.execute(
                    "SELECT team_id,name FROM teams WHERE active=1 AND team_id<>?",
                    (team_id,),
                ).fetchall()
            }
            assignments = {
                row["rep_key"]: int(row["team_id"])
                for row in con.execute(
                    "SELECT rep_key,team_id FROM rep_team_assignments"
                ).fetchall()
            }
            source_reps = [
                dict(row)
                for row in con.execute("SELECT rep_key,team FROM reps").fetchall()
            ]

            effective_members = []
            for rep in source_reps:
                rep_key = str(rep.get("rep_key") or "")
                assigned_id = assignments.get(rep_key)
                if assigned_id == team_id:
                    effective_members.append(rep_key)
                    continue
                if assigned_id:
                    continue
                if str(rep.get("team") or "").strip().lower() == team_name.lower():
                    effective_members.append(rep_key)

            if effective_members and not active_destinations:
                raise ValueError(
                    "This team has reps. Create another team before deleting it."
                )
            missing = [
                rep_key for rep_key in effective_members if rep_key not in requested
            ]
            if missing:
                raise ValueError(
                    "Every rep on this team must be reassigned before the team can be deleted."
                )

            for rep_key in effective_members:
                destination_id = requested[rep_key]
                if destination_id == team_id or destination_id not in active_destinations:
                    raise ValueError("Choose a valid destination team for every rep.")
                con.execute(
                    "INSERT INTO rep_team_assignments(rep_key,team_id) VALUES(?,?) "
                    "ON CONFLICT(rep_key) DO UPDATE SET team_id=excluded.team_id",
                    (rep_key, destination_id),
                )

            con.execute("DELETE FROM teams WHERE team_id=?", (team_id,))

        self.meta.bump("organization_version")
        return {
            "team_id": team_id,
            "name": team_name,
            "logo_path": logo_path,
            "member_count": len(effective_members),
            "destination_team_ids": sorted(set(requested.values())),
        }

    def set_leader(self, team_id, name, role):
        lead_name = str(name or "").strip()
        lead_role = str(role or "Sales Manager").strip() or "Sales Manager"
        with database.connect() as con:
            con.execute("DELETE FROM team_leads WHERE team_id=?", (int(team_id),))
            lead_id = None
            if lead_name:
                cur = con.execute(
                    "INSERT INTO team_leads(team_id,lead_name,lead_role) VALUES(?,?,?)",
                    (int(team_id), lead_name, lead_role),
                )
                lead_id = cur.lastrowid
        self.meta.bump("organization_version")
        return lead_id

    def delete_leader(self, lead_id):
        with database.connect() as con:
            con.execute("DELETE FROM team_leads WHERE lead_id=?", (int(lead_id),))
        self.meta.bump("organization_version")

    def assign_reps(self, assignments):
        with database.connect() as con:
            for item in assignments:
                rep_key = str(item.get("rep_key") or "").strip()
                team_id = item.get("team_id")
                if not rep_key:
                    continue
                if team_id in (None, "", 0, "0"):
                    con.execute(
                        "DELETE FROM rep_team_assignments WHERE rep_key=?",
                        (rep_key,),
                    )
                else:
                    con.execute(
                        "INSERT INTO rep_team_assignments(rep_key,team_id) VALUES(?,?) "
                        "ON CONFLICT(rep_key) DO UPDATE SET team_id=excluded.team_id",
                        (rep_key, int(team_id)),
                    )
        self.meta.bump("organization_version")

    def set_logo(self, team_id, path):
        with database.connect() as con:
            con.execute(
                "UPDATE teams SET logo_path=? WHERE team_id=?",
                (str(path or "").strip() or None, int(team_id)),
            )
        self.meta.bump("organization_version")
