from pgvector.sqlalchemy import VECTOR
from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass



class GroupMessage(Base):
    __tablename__ = "group_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    sender_role: Mapped[str] = mapped_column(String, nullable=False)
    sender_user: Mapped[str] = mapped_column(String, nullable=False)
    sender_name: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meet_link: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    clerk_user_id: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    roll_no: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    password: Mapped[str | None] = mapped_column(String, nullable=True)
    year: Mapped[str | None] = mapped_column(String, nullable=True)


class EnrollmentCode(Base):
    __tablename__ = "enrollment_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    roll_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    year: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    used_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    used_by_clerk_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    revoked_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    year: Mapped[str | None] = mapped_column(String, nullable=True)
    group_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_name: Mapped[str | None] = mapped_column(String, nullable=True)
    project_abstract: Mapped[str | None] = mapped_column(String, nullable=True)
    team_name: Mapped[str | None] = mapped_column(String, nullable=True)
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    submitted_by_student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="SET NULL"), nullable=True
    )
    assigned_mentor_id: Mapped[int | None] = mapped_column(
        ForeignKey("mentors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mentor_assigned_at: Mapped[str | None] = mapped_column(String, nullable=True)
    # Cloudflare Qwen3 embeddings are 1024-dimensional and nullable until indexed.
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(1024), nullable=True)


class Mentor(Base):
    __tablename__ = "mentors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    clerk_user_id: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=True)
    password: Mapped[str | None] = mapped_column(String, nullable=True)


class MentorStudent(Base):
    __tablename__ = "mentor_students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    mentor_name: Mapped[str] = mapped_column(String, nullable=False)
    mentor_key: Mapped[str] = mapped_column(String, index=True, nullable=False)
    student_name: Mapped[str] = mapped_column(String, nullable=False)
    prn: Mapped[str | None] = mapped_column(String, nullable=True)
    group_name: Mapped[str | None] = mapped_column(String, nullable=True)
    project_name: Mapped[str | None] = mapped_column(String, nullable=True)
    year: Mapped[str | None] = mapped_column(String, nullable=True)


class MentorReview(Base):
    __tablename__ = "mentor_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    mentor_name: Mapped[str] = mapped_column(String, nullable=False)
    mentor_key: Mapped[str] = mapped_column(String, index=True, nullable=False)
    group_name: Mapped[str] = mapped_column(String, nullable=False)
    review_type: Mapped[str] = mapped_column(String, nullable=False)
    review_date: Mapped[str] = mapped_column(String, nullable=False)
    review_time: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="scheduled")
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Team names are not unique in existing project data; team_code is the identifier.
    team_name: Mapped[str | None] = mapped_column(String, nullable=True)
    password: Mapped[str | None] = mapped_column(String, nullable=True)
    year: Mapped[str | None] = mapped_column(String, nullable=True)
    mentor_name: Mapped[str | None] = mapped_column(String, nullable=True)
    team_code: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    max_members: Mapped[int | None] = mapped_column(Integer, default=4, nullable=True)
    created_by_student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="SET NULL"), nullable=True, index=True
    )


class TeamMember(Base):
    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    roll_no: Mapped[str | None] = mapped_column(String, nullable=True)


class TeamInvitation(Base):
    __tablename__ = "team_invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    team_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    inviter_roll_no: Mapped[str] = mapped_column(String, nullable=False)
    invitee_roll_no: Mapped[str] = mapped_column(String, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String, index=True, nullable=False, default="pending")
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    responded_at: Mapped[str | None] = mapped_column(String, nullable=True)


class ApiRateLimitBucket(Base):
    """Shared fixed-window counters, stored in PostgreSQL across API workers."""

    __tablename__ = "api_rate_limit_buckets"

    bucket_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
