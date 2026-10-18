"""Validate and atomically replace team data from a mentor's group workbook."""

from collections import defaultdict
from uuid import uuid4

from sqlalchemy import text

from group_connect import room_id
from mentor_roster import mentor_key, parse_mentor_roster
from models import GroupMessage, Mentor, MentorReview, MentorStudent, Project, Team, TeamInvitation, TeamMember
from utils import generate_team_code


class TeamSheetError(ValueError):
    def __init__(self, message: str, *, conflicts: list[dict] | None = None):
        super().__init__(message)
        self.conflicts = conflicts or []


def parse_team_sheet(content: bytes, resolutions: dict[str, str] | None = None) -> dict[str, list[dict]]:
    rows = parse_mentor_roster(content, "")
    by_prn: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        prn = row["prn"].strip().casefold()
        group = row["group_name"].strip()
        if not prn or not group or not group.isdecimal() or int(group) < 1 or not row["mentor_key"]:
            raise TeamSheetError("Every student needs a PRN, positive group number, and guide.")
        row["group_name"] = str(int(group))
        by_prn[prn].append(row)

    choices = {key.strip().casefold(): str(value).strip() for key, value in (resolutions or {}).items()}
    conflicts = [
        {"prn": prn, "groups": sorted({row["group_name"] for row in entries}, key=int)}
        for prn, entries in by_prn.items() if len(entries) > 1
    ]
    unresolved = [conflict for conflict in conflicts if choices.get(conflict["prn"]) not in conflict["groups"]]
    if unresolved:
        raise TeamSheetError("Choose one group for each duplicate PRN before importing.", conflicts=unresolved)
    selected = []
    for prn, entries in by_prn.items():
        chosen = choices.get(prn)
        matches = [row for row in entries if row["group_name"] == chosen] if chosen else entries
        if len(matches) != 1:
            raise TeamSheetError(f"PRN {prn} occurs more than once in the same group.")
        selected.append(matches[0])

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in selected:
        groups[row["group_name"]].append(row)
    for number, members in groups.items():
        if len(members) > 4:
            raise TeamSheetError(f"Group {number} has more than four distinct students.")
        if len({row["mentor_key"] for row in members}) != 1:
            raise TeamSheetError(f"Group {number} has conflicting guides.")
        if len({row["project_name"].strip().casefold() for row in members if row["project_name"]}) > 1:
            raise TeamSheetError(f"Group {number} has conflicting project titles.")
    if not groups:
        raise TeamSheetError("The workbook contains no groups.")
    return dict(groups)


def replace_team_sheet(db, groups: dict[str, list[dict]]) -> dict[str, int]:
    """Replace all sheet-controlled teams, memberships, invitations and roster rows."""
    if db.bind.dialect.name == "postgresql":
        db.execute(text(
            "LOCK TABLE teams, team_members, team_invitations, mentor_students, projects, "
            "group_messages, mentor_reviews "
            "IN SHARE ROW EXCLUSIVE MODE"
        ))
    teams = db.query(Team).order_by(Team.id).all()
    projects = {row.team_id: row for row in db.query(Project).filter(Project.team_id.is_not(None)).all()}
    mapped = {team.sheet_group_no: team for team in teams if team.sheet_group_no}
    incoming_prns = {row["prn"].strip().casefold() for members in groups.values() for row in members}
    mapped_project_ids = {mapped[number].id for number in groups if number in mapped}
    for member in db.query(TeamMember.team_id, TeamMember.roll_no).all():
        if (member.team_id in projects and member.team_id not in mapped_project_ids
                and member.roll_no and member.roll_no.strip().casefold() in incoming_prns):
            raise TeamSheetError(
                f"Existing project team {member.team_id} has students in this sheet but no verified group mapping."
            )
    for number, members in groups.items():
        project = projects.get(mapped[number].id) if number in mapped else None
        if project and project.assigned_mentor_id:
            owner = db.get(Mentor, project.assigned_mentor_id)
            if not owner or mentor_key(owner.username) != members[0]["mentor_key"]:
                raise TeamSheetError(f"Group {number} conflicts with its selected project's mentor.")

    old_rooms: dict[str, set[str]] = defaultdict(set)
    old_room_labels: dict[str, tuple[str, str]] = {}
    for row in db.query(MentorStudent).all():
        if row.group_name and row.prn:
            identity = room_id(row.mentor_key, row.group_name)
            old_rooms[identity].add(row.prn.strip().casefold())
            old_room_labels[identity] = (row.mentor_key, row.group_name)
    new_rooms: dict[str, set[str]] = defaultdict(set)
    for number, members in groups.items():
        project = projects.get(mapped[number].id) if number in mapped else None
        label = str(project.group_no) if project and project.group_no else number
        for row in members:
            new_rooms[room_id(row["mentor_key"], label)].add(row["prn"].strip().casefold())
    for identity, old_members in old_rooms.items():
        if new_rooms.get(identity) == old_members:
            continue
        marker = uuid4().hex
        db.query(GroupMessage).filter(GroupMessage.room_id == identity).update(
            {GroupMessage.room_id: f"archived:{marker}"}, synchronize_session=False
        )
        key, label = old_room_labels[identity]
        for review in db.query(MentorReview).filter(MentorReview.mentor_key == key).all():
            if room_id(review.mentor_key, review.group_name) == identity:
                review.group_name = f"Archived {label} ({marker})"
                if review.status == "scheduled":
                    review.status = "archived"

    db.query(TeamInvitation).delete(synchronize_session=False)
    db.query(TeamMember).delete(synchronize_session=False)
    db.query(MentorStudent).delete(synchronize_session=False)
    db.flush()
    for team in teams:
        if team.sheet_group_no not in groups:
            if team.id in projects:
                team.sheet_group_no = None  # Retain the student's old project on its old team.
            else:
                db.delete(team)
    db.flush()

    used_codes = {team.team_code for team in teams if team.team_code}
    for number in sorted(groups, key=int):
        members = groups[number]
        team = mapped.get(number)
        if team is None:
            code = generate_team_code()
            while code in used_codes:
                code = generate_team_code()
            used_codes.add(code)
            team = Team(sheet_group_no=number, team_code=code, max_members=4)
            db.add(team)
            db.flush()
        team.team_name = f"Group {number}"
        team.max_members = 4
        team.created_by_student_id = None
        project = projects.get(team.id)
        if project:
            project.team_name = team.team_name
        for row in members:
            db.add(TeamMember(team_id=team.id, roll_no=row["prn"].strip()))
            db.add(MentorStudent(
                mentor_name=row["mentor_name"], mentor_key=row["mentor_key"],
                student_name=row["student_name"], prn=row["prn"].strip(),
                group_name=str(project.group_no) if project and project.group_no else number,
                project_name=project.project_name if project else row["project_name"] or None,
                year=row["year"] or None,
            ))
    db.flush()
    if db.bind.dialect.name == "postgresql":
        db.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_team_members_roll_no_normalized "
            "ON team_members (lower(btrim(roll_no)))"
        ))
    return {"groups": len(groups), "memberships": sum(map(len, groups.values())),
            "retained_projects": len(projects)}
