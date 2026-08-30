from __future__ import annotations

from stats_core.storage import sqlite as database


class OrganizationRepository:
    def list_team_names(self):
        return database.list_teams()

    def definitions(self, include_inactive=False):
        return database.get_team_definitions(include_inactive=include_inactive)

    def save_builder(self, team_id, name, leader_name, leader_role, member_rep_keys):
        return database.save_team_builder(team_id, name, leader_name, leader_role, member_rep_keys)

    def create(self, name):
        return database.create_team(name)

    def rename(self, team_id, name):
        return database.rename_team(team_id, name)

    def delete(self, team_id, reassignments):
        return database.delete_team(team_id, reassignments)

    def set_leader(self, team_id, name, role):
        return database.set_team_lead(team_id, name, role)

    def delete_leader(self, lead_id):
        return database.delete_team_lead(lead_id)

    def assign_reps(self, assignments):
        return database.set_rep_team_assignments(assignments)

    def set_logo(self, team_id, path):
        return database.set_team_logo(team_id, path)
