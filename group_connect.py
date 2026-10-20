"""Shared mentor/student rooms, derived from the mentor's assigned roster."""

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, text

from mentor_roster import mentor_key
from models import GroupMessage, Mentor, MentorReview, MentorStudent, Project, Student, Team, TeamMember
from project_access import roster_for_project_owners


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    group_id: str = Field(min_length=1, max_length=200)
    text: str = Field(default="", max_length=4000)
    meet_link: str = Field(default="", max_length=200)


def room_id(key, number):
    return json.dumps([key, number.strip().casefold()], ensure_ascii=False, separators=(",", ":"))


def lock_roster_for_message_access(db):
    # A full sheet import rotates rooms when membership changes. Keep the
    # authorization check and message read/write in the same roster version.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("LOCK TABLE mentor_students IN SHARE MODE"))


def assigned_rooms(db, role, user):
    user = user.strip()
    if role == "mentor":
        account = db.query(Mentor).filter(func.lower(Mentor.username) == user.lower()).first()
        if not account:
            raise HTTPException(404, "Mentor account not found.")
        roster = db.query(MentorStudent).filter(MentorStudent.mentor_key == mentor_key(account.username)).all()
        roster = roster_for_project_owners(db, roster)
        name = account.username
    else:
        account = db.query(Student).filter(func.lower(Student.roll_no) == user.lower()).first()
        if not account:
            raise HTTPException(404, "Student account not found.")
        assignments = db.query(MentorStudent).filter(func.lower(MentorStudent.prn) == user.lower()).all()
        assignments = roster_for_project_owners(db, assignments)
        allowed = {room_id(row.mentor_key, row.group_name) for row in assignments if row.group_name and row.group_name.strip()}
        keys = {row.mentor_key for row in assignments}
        roster = db.query(MentorStudent).filter(MentorStudent.mentor_key.in_(keys)).all() if keys else []
        roster = roster_for_project_owners(db, roster)
        roster = [row for row in roster if row.group_name and room_id(row.mentor_key, row.group_name) in allowed]
        name = assignments[0].student_name if assignments else account.roll_no
    members_by_team = defaultdict(list)
    for member in db.query(TeamMember).all():
        if member.team_id and member.roll_no:
            members_by_team[member.team_id].append(member.roll_no)
    linked_rolls = {roll.strip().casefold() for rolls in members_by_team.values() for roll in rolls}
    roster = [row for row in roster if not row.prn or row.prn.strip().casefold() not in linked_rolls]
    groups = {}
    for row in roster:
        if not row.group_name or not row.group_name.strip():
            continue
        number = row.group_name.strip()
        identity = room_id(row.mentor_key, number)
        group = groups.setdefault(identity, {
            "id": identity, "number": number,
            "name": number if re.match(r"group\b", number, re.I) else f"Group {number}",
            "mentor": row.mentor_name, "mentor_key": row.mentor_key,
            "project": "No Project", "members": [], "reviews": [],
        })
        group["members"].append(row.student_name)
        if row.project_name and row.project_name.strip().lower() != "no project":
            group["project"] = row.project_name
    # Team membership is authoritative. Roster rows are retained only for
    # students who have not yet been linked to a Team in the database.
    roster_names = {row.prn.strip().casefold(): row.student_name
                    for row in db.query(MentorStudent).all() if row.prn and row.student_name}
    roster_titles = {row.prn.strip().casefold(): row.project_name
                     for row in db.query(MentorStudent).all() if row.prn and row.project_name}
    for team in db.query(Team).all():
        rolls = members_by_team.get(team.id, [])
        if not rolls or (role == "student" and user.casefold() not in {roll.strip().casefold() for roll in rolls}):
            continue
        project = db.query(Project).filter(Project.team_id == team.id).first()
        owner = db.get(Mentor, project.assigned_mentor_id) if project and project.assigned_mentor_id else None
        mentor_name = owner.username if owner else team.mentor_name
        if role == "mentor" and (not mentor_name or mentor_key(mentor_name) != mentor_key(name)):
            continue
        number = str(team.sheet_group_no or (project.group_no if project else None) or team.id)
        key = mentor_key(mentor_name) if mentor_name else "unassigned"
        identity = room_id(key, number)
        title = (project.project_name if project else None) or next(
            (roster_titles.get(roll.strip().casefold()) for roll in rolls
             if roster_titles.get(roll.strip().casefold())), None) or (
            team.team_name if team.created_by_student_id is None and team.team_name
            and team.team_name.strip().casefold() not in {number.casefold(), f"group {number}".casefold()}
            else None) or "No Project"
        groups[identity] = {
            "id": identity, "number": number, "name": f"Group {number}",
            "mentor": mentor_name or "Not assigned", "mentor_key": key,
            "project": title,
            "members": [roster_names.get(roll.strip().casefold(), roll) for roll in rolls],
            "reviews": [],
        }
    if groups:
        keys = {group["mentor_key"] for group in groups.values()}
        reviews = db.query(MentorReview).filter(
            MentorReview.mentor_key.in_(keys), MentorReview.status == "scheduled",
        ).order_by(MentorReview.review_date, MentorReview.review_time).all()
        for review in reviews:
            group = groups.get(room_id(review.mentor_key, review.group_name))
            if group:
                group["reviews"].append({"type": review.review_type, "date": review.review_date,
                                         "time": review.review_time, "notes": review.notes or ""})
    return sorted(groups.values(), key=lambda group: group["name"].casefold()), account, name


def verified_identity(request: Request) -> tuple[str, str]:
    """Read the role and identifier resolved by the FastAPI Clerk middleware."""
    profile = getattr(request.state, "profile", None)
    if not profile:
        raise HTTPException(401, "A linked Clerk profile is required.")
    return profile["role"], profile["identifier"]


def create_router(session_factory):
    router = APIRouter(prefix="/group-connect")

    @router.get("/groups")
    def get_groups(request: Request):
        role, user = verified_identity(request)
        with session_factory() as db:
            groups, _, _ = assigned_rooms(db, role, user)
            return [{key: value for key, value in group.items() if key != "mentor_key"} for group in groups]

    @router.get("/messages")
    def get_messages(request: Request, group_id: Annotated[str, Query(min_length=1, max_length=200)]):
        role, user = verified_identity(request)
        with session_factory() as db:
            lock_roster_for_message_access(db)
            groups, _, _ = assigned_rooms(db, role, user)
            if not any(group["id"] == group_id for group in groups):
                raise HTTPException(403, "You are not assigned to this group.")
            # Bound response size while keeping the most recent conversation in order.
            messages = db.query(GroupMessage).filter(GroupMessage.room_id == group_id).order_by(
                GroupMessage.id.desc()).limit(200).all()
            return [message_payload(message, role, user) for message in reversed(messages)]

    @router.post("/messages", status_code=201)
    def send_message(data: MessageRequest, request: Request):
        role, user = verified_identity(request)
        text, link = data.text.strip(), data.meet_link.strip()
        if not text and not link:
            raise HTTPException(400, "Enter a message or share a meeting link.")
        if link and not re.fullmatch(r"https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}", link):
            raise HTTPException(400, "Paste a valid Google Meet link, such as https://meet.google.com/abc-defg-hij.")
        with session_factory() as db:
            lock_roster_for_message_access(db)
            groups, account, name = assigned_rooms(db, role, user)
            if not any(group["id"] == data.group_id for group in groups):
                raise HTTPException(403, "You are not assigned to this group.")
            message = GroupMessage(
                room_id=data.group_id, sender_role=role,
                sender_user=account.username if role == "mentor" else account.roll_no,
                sender_name=name, text=text, meet_link=link or None,
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            db.add(message)
            db.commit()
            db.refresh(message)
            return message_payload(message, role, user)

    return router


def message_payload(message, role, user):
    return {"id": message.id, "role": message.sender_role,
            "is_own": message.sender_role == role and message.sender_user.strip().casefold() == user.strip().casefold(),
            "name": message.sender_name, "text": message.text,
            "meet_link": message.meet_link, "created_at": message.created_at}
