"""Shared mentor/student rooms, derived from the mentor's assigned roster."""

import json
import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

from mentor_roster import mentor_key
from models import GroupMessage, Mentor, MentorReview, MentorStudent, Student


class MessageRequest(BaseModel):
    role: Literal["mentor", "student"]
    user: str
    group_id: str
    text: str = Field(default="", max_length=4000)
    meet_link: str = Field(default="", max_length=200)


def room_id(key, number):
    return json.dumps([key, number.strip().casefold()], ensure_ascii=False, separators=(",", ":"))


def assigned_rooms(db, role, user):
    user = user.strip()
    if role == "mentor":
        account = db.query(Mentor).filter(func.lower(Mentor.username) == user.lower()).first()
        if not account:
            raise HTTPException(404, "Mentor account not found.")
        roster = db.query(MentorStudent).filter(MentorStudent.mentor_key == mentor_key(account.username)).all()
        name = account.username
    else:
        account = db.query(Student).filter(func.lower(Student.roll_no) == user.lower()).first()
        if not account:
            raise HTTPException(404, "Student account not found.")
        assignments = db.query(MentorStudent).filter(func.lower(MentorStudent.prn) == user.lower()).all()
        allowed = {room_id(row.mentor_key, row.group_name) for row in assignments if row.group_name and row.group_name.strip()}
        keys = {row.mentor_key for row in assignments}
        roster = db.query(MentorStudent).filter(MentorStudent.mentor_key.in_(keys)).all() if keys else []
        roster = [row for row in roster if row.group_name and room_id(row.mentor_key, row.group_name) in allowed]
        name = assignments[0].student_name if assignments else account.roll_no
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


def create_router(session_factory):
    router = APIRouter(prefix="/group-connect")

    @router.get("/groups")
    def get_groups(role: Literal["mentor", "student"], user: str):
        with session_factory() as db:
            groups, _, _ = assigned_rooms(db, role, user)
            return groups

    @router.get("/messages")
    def get_messages(role: Literal["mentor", "student"], user: str, group_id: str):
        with session_factory() as db:
            groups, _, _ = assigned_rooms(db, role, user)
            if not any(group["id"] == group_id for group in groups):
                raise HTTPException(403, "You are not assigned to this group.")
            # Bound response size while keeping the most recent conversation in order.
            messages = db.query(GroupMessage).filter(GroupMessage.room_id == group_id).order_by(
                GroupMessage.id.desc()).limit(200).all()
            return [message_payload(message) for message in reversed(messages)]

    @router.post("/messages", status_code=201)
    def send_message(data: MessageRequest):
        text, link = data.text.strip(), data.meet_link.strip()
        if not text and not link:
            raise HTTPException(400, "Enter a message or share a meeting link.")
        if link and not re.fullmatch(r"https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}", link):
            raise HTTPException(400, "Paste a valid Google Meet link, such as https://meet.google.com/abc-defg-hij.")
        with session_factory() as db:
            groups, account, name = assigned_rooms(db, data.role, data.user)
            if not any(group["id"] == data.group_id for group in groups):
                raise HTTPException(403, "You are not assigned to this group.")
            message = GroupMessage(
                room_id=data.group_id, sender_role=data.role,
                sender_user=account.username if data.role == "mentor" else account.roll_no,
                sender_name=name, text=text, meet_link=link or None,
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            db.add(message)
            db.commit()
            db.refresh(message)
            return message_payload(message)

    return router


def message_payload(message):
    return {"id": message.id, "role": message.sender_role, "user": message.sender_user,
            "name": message.sender_name, "text": message.text,
            "meet_link": message.meet_link, "created_at": message.created_at}
