"""Shared portal visibility rules for canonical team projects."""

from sqlalchemy import func, or_

from mentor_roster import mentor_key
from models import Mentor, Project, Team, TeamMember


def mentor_projects(db, mentor_id: int):
    """Legacy/orphaned rows stay private until their relationships are verified."""
    return db.query(Project).join(Team, Project.team_id == Team.id).filter(
        or_(Project.assigned_mentor_id.is_(None), Project.assigned_mentor_id == mentor_id)
    )


def project_summary(project, mentor_id: int):
    """Only fields rendered by the mentor project list; AI loads its own context."""
    return {
        "id": project.id,
        "year": project.year,
        "group_no": project.group_no,
        "project_name": project.project_name,
        "team": project.team_name,
        "assigned_to_me": project.assigned_mentor_id == mentor_id,
        "can_assign": project.assigned_mentor_id is None,
    }


def roster_for_project_owners(db, roster):
    """Stale roster links cannot expose a team assigned to a different mentor."""
    rolls = {row.prn.strip().lower() for row in roster if row.prn and row.prn.strip()}
    if not rolls:
        return roster
    owners = {}
    rows = db.query(TeamMember.roll_no, Mentor.username).join(
        Project, Project.team_id == TeamMember.team_id
    ).join(Team, Team.id == Project.team_id).join(
        Mentor, Mentor.id == Project.assigned_mentor_id
    ).filter(func.lower(TeamMember.roll_no).in_(rolls)).all()
    for roll, username in rows:
        owners.setdefault(roll.strip().lower(), set()).add(mentor_key(username))
    return [
        row for row in roster
        if not row.prn or not row.prn.strip() or
        not (owners.get(row.prn.strip().lower(), set()) - {row.mentor_key})
    ]
