"""Admin-only reconciliation of legacy projects; preview is the default.

There is no HTTP endpoint for this tool. Run it with trusted database credentials.
Never infer team or mentor ownership from matching names.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import func

from mentor_roster import mentor_key
from models import Mentor, MentorStudent, Project, Student, Team, TeamMember


def legacy_inventory(db):
    """Provide identifiers for reconciliation without dumping project abstracts."""
    return [
        {
            "project_id": project.id,
            "project_name": project.project_name,
            "team_label": project.team_name,
            "year": project.year,
            "assigned_mentor_id": project.assigned_mentor_id,
        }
        for project in db.query(Project).outerjoin(Team, Project.team_id == Team.id)
        .filter(Team.id.is_(None)).order_by(Project.id).all()
    ]


def reconcile_projects(db, mappings):
    """Stage explicit trusted mappings in the caller's transaction; never commit."""
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("The mapping must be a nonempty JSON array.")
    project_ids, team_ids = set(), set()
    validated = []
    for mapping in mappings:
        if not isinstance(mapping, dict) or set(mapping) != {"project_id", "team_id", "mentor_id"}:
            raise ValueError("Each mapping requires exactly project_id, team_id, and mentor_id.")
        if any(type(value) is not int or value < 1 for value in mapping.values()):
            raise ValueError("Mapping IDs must be positive integers.")
        if mapping["project_id"] in project_ids or mapping["team_id"] in team_ids:
            raise ValueError("A project or team cannot appear in multiple mappings.")
        project_ids.add(mapping["project_id"])
        team_ids.add(mapping["team_id"])
        validated.append(mapping)

    # Lock teams before projects, in ID order, matching portal mutation order.
    teams = {team.id: team for team in db.query(Team).filter(Team.id.in_(team_ids))
             .order_by(Team.id).with_for_update().all()}
    projects = {project.id: project for project in db.query(Project).filter(Project.id.in_(project_ids))
                .order_by(Project.id).with_for_update().all()}
    staged = []
    for mapping in validated:
        project = projects.get(mapping["project_id"])
        team = teams.get(mapping["team_id"])
        mentor = db.query(Mentor).filter(Mentor.id == mapping["mentor_id"]).first()
        if not project or not team or not mentor:
            raise ValueError("A mapped project, team, or mentor does not exist.")
        if project.team_id is not None:
            raise ValueError(f"Project {project.id} already has a team relationship.")
        if project.assigned_mentor_id not in (None, mentor.id):
            raise ValueError(f"Project {project.id} is already assigned to another mentor.")
        if db.query(Project.id).filter(Project.team_id == team.id).first():
            raise ValueError(f"Team {team.id} already has a current project; it cannot be overwritten.")
        members = db.query(TeamMember).filter(TeamMember.team_id == team.id).all()
        rolls = [member.roll_no.strip().lower() for member in members if member.roll_no and member.roll_no.strip()]
        if len(rolls) < 2 or len(rolls) != len(members) or len(rolls) != len(set(rolls)):
            raise ValueError(f"Team {team.id} needs at least two distinct valid student memberships.")
        for roll in rolls:
            accounts = db.query(Student.id).filter(func.lower(Student.roll_no) == roll).all()
            memberships = db.query(TeamMember.id).filter(func.lower(TeamMember.roll_no) == roll).all()
            if len(accounts) != 1 or len(memberships) != 1:
                raise ValueError(f"Team {team.id} has an ambiguous or missing student relationship.")
        conflicting_roster = db.query(MentorStudent.id).filter(
            func.lower(MentorStudent.prn).in_(rolls),
            MentorStudent.mentor_key != mentor_key(mentor.username),
        ).first()
        if conflicting_roster:
            raise ValueError(f"Team {team.id} has a student assigned to another mentor.")
        roster = db.query(MentorStudent).filter(func.lower(MentorStudent.prn).in_(rolls)).all()
        if len(roster) != len({row.prn.strip().lower() for row in roster}):
            raise ValueError(f"Team {team.id} has duplicate roster identities.")
        staged.append((project, team, mentor, rolls, roster))

    # Apply only after every mapping validates. Content and vectors are preserved.
    for project, team, mentor, rolls, roster in staged:
        project.team_id = team.id
        project.team_name = team.team_name
        project.assigned_mentor_id = mentor.id
        project.mentor_assigned_at = project.mentor_assigned_at or datetime.now().isoformat(timespec="seconds")
        roster_by_roll = {row.prn.strip().lower(): row for row in roster}
        for roll in rolls:
            entry = roster_by_roll.get(roll)
            if entry is None:
                student = db.query(Student).filter(func.lower(Student.roll_no) == roll).one()
                entry = MentorStudent(
                    mentor_name=mentor.username, mentor_key=mentor_key(mentor.username),
                    student_name=student.roll_no, prn=student.roll_no,
                    group_name=team.team_name, year=student.year or team.year,
                )
                db.add(entry)
            entry.project_name = project.project_name
    return validated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, help="Administrator-verified JSON mapping file")
    parser.add_argument("--apply", action="store_true", help="Commit a validated mapping; default is preview")
    args = parser.parse_args()
    if args.apply and not args.mapping:
        parser.error("--apply requires --mapping")
    from database import SessionLocal

    with SessionLocal() as db:
        if not args.mapping:
            print(json.dumps(legacy_inventory(db), indent=2))
            return
        try:
            mappings = json.loads(args.mapping.read_text(encoding="utf-8"))
            result = reconcile_projects(db, mappings)
            if args.apply:
                db.commit()
            else:
                db.rollback()
            print(json.dumps({"applied": args.apply, "mappings": result}, indent=2))
        except (ValueError, OSError) as error:
            db.rollback()
            parser.error(str(error))


if __name__ == "__main__":
    main()
