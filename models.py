from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class GroupMessage(Base):
    __tablename__ = "group_messages"

    id = Column(Integer, primary_key=True)
    room_id = Column(String, index=True, nullable=False)
    sender_role = Column(String, nullable=False)
    sender_user = Column(String, nullable=False)
    sender_name = Column(String, nullable=False)
    text = Column(Text, nullable=False, default="")
    meet_link = Column(String, nullable=True)
    created_at = Column(String, nullable=False)

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    roll_no = Column(String, unique=True, index=True)
    password = Column(String)
    year = Column(String)

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    year = Column(String)
    group_no = Column(Integer)
    project_name = Column(String)
    project_abstract = Column(String)
    team_name = Column(String, nullable=True)

class Mentor(Base):
    __tablename__ = "mentors"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)


class MentorStudent(Base):
    __tablename__ = "mentor_students"

    id = Column(Integer, primary_key=True, index=True)
    mentor_name = Column(String, nullable=False)
    mentor_key = Column(String, index=True, nullable=False)
    student_name = Column(String, nullable=False)
    prn = Column(String, nullable=True)
    group_name = Column(String, nullable=True)
    project_name = Column(String, nullable=True)
    year = Column(String, nullable=True)


class MentorReview(Base):
    __tablename__ = "mentor_reviews"

    id = Column(Integer, primary_key=True, index=True)
    mentor_name = Column(String, nullable=False)
    mentor_key = Column(String, index=True, nullable=False)
    group_name = Column(String, nullable=False)
    review_type = Column(String, nullable=False)
    review_date = Column(String, nullable=False)
    review_time = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="scheduled")
    created_at = Column(String, nullable=False)
    completed_at = Column(String, nullable=True)


# 🔥 Team table
class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    team_name = Column(String, unique=True)
    password = Column(String)
    year = Column(String)
    mentor_name = Column(String)
    team_code = Column(String, unique=True)
    description = Column(String, nullable=True)
    max_members = Column(Integer, default=4)


# 🔥 Members table
class TeamMember(Base):
    __tablename__ = "team_members"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer)
    roll_no = Column(String)


class TeamInvitation(Base):
    __tablename__ = "team_invitations"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, index=True, nullable=False)
    inviter_roll_no = Column(String, nullable=False)
    invitee_roll_no = Column(String, index=True, nullable=False)
    status = Column(String, index=True, nullable=False, default="pending")
    created_at = Column(String, nullable=False)
    responded_at = Column(String, nullable=True)
