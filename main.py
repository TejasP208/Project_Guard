from contextlib import asynccontextmanager
import logging
from datetime import datetime
from typing import Annotated
from zipfile import BadZipFile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from openpyxl.utils.exceptions import InvalidFileException
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from axiom_ai import Chatbot_stream
from database import SessionLocal, enable_pgvector, engine, migrate_database
from mentor_roster import mentor_key, parse_mentor_roster
from models import Base, Mentor, MentorReview, MentorStudent, Project, Student, Team, TeamInvitation, TeamMember
from nlp.checker import run_plagiarism_check
from group_connect import create_router
from nlp.extractor import DocumentExtractionError, DocumentLimitError, DocumentValidationError
from passwords import hash_password, verify_password
from utils import generate_team_code
from embeddings import CloudflareEmbeddingClient


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Create all runtime tables in PostgreSQL only after pgvector is enabled.
    enable_pgvector()
    Base.metadata.create_all(bind=engine)
    migrate_database()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(create_router(lambda: SessionLocal()))
logger = logging.getLogger(__name__)

MAX_PLAGIARISM_UPLOAD_BYTES = 20 * 1024 * 1024

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Models
class SignupRequest(BaseModel):
    roll_no: str
    year: str
    password: str

class LoginRequest(BaseModel):
    roll_no: str
    password: str

class ProjectSubmission(BaseModel):
    roll_no: str
    group_no: int = 0
    project_name: str
    project_abstract: str = ""

class CreateTeamRequest(BaseModel):
    team_name: str
    description: str = ""
    max_members: int = 4
    roll_no: str | None = None

class JoinTeamRequest(BaseModel):
    team_code: str
    roll_no: str

class LeaveTeamRequest(BaseModel):
    roll_no: str

class TeamInviteRequest(BaseModel):
    inviter_roll_no: str
    invitee_roll_no: str

class TeamInviteResponse(BaseModel):
    roll_no: str
    action: str

class MentorSignupRequest(BaseModel):
    username: str
    password: str

class MentorLoginRequest(BaseModel):
    username: str
    password: str

class MentorStudentUpdate(BaseModel):
    mentor_user: str
    student_name: str
    prn: str = ""
    group_number: str = ""
    project_name: str = ""
    year: str = ""

class MentorStudentCreate(MentorStudentUpdate):
    transfer_existing: bool = False

class MentorReviewCreate(BaseModel):
    mentor_user: str
    group_number: str
    review_type: str
    review_date: str
    review_time: str
    notes: str = ""

class MentorReviewStatus(BaseModel):
    mentor_user: str
    status: str

class AxiomChatTurn(BaseModel):
    role: str
    content: str

class MentorAxiomRequest(BaseModel):
    question: str
    project_title: str
    project_abstract: str = ""
    group_name: str = ""
    year: str = ""
    history: list[AxiomChatTurn] = Field(default_factory=list)

# Endpoints
@app.get("/chat-stream")
async def chat_stream(prompt: str):
    return StreamingResponse(
        Chatbot_stream(prompt),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/mentor/axiom-stream")
async def mentor_axiom_stream(data: MentorAxiomRequest):
    question = data.question.strip()
    title = data.project_title.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Enter a question for Axiom AI.")
    if not title:
        raise HTTPException(status_code=400, detail="Project title is required.")
    history_lines = []
    for turn in data.history[-8:]:
        role = "Mentor" if turn.role == "user" else "Axiom AI"
        content = " ".join(turn.content.split())[:2000]
        if content:
            history_lines.append(f"{role}: {content}")
    prompt = "\n".join([
        "Help a mentor review the following academic project.",
        f"Project title: {title[:500]}",
        f"Project abstract: {(data.project_abstract.strip() or 'Not provided')[:5000]}",
        f"Group: {(data.group_name.strip() or 'Not provided')[:200]}",
        f"Year: {(data.year.strip() or 'Not provided')[:100]}",
        "Recent conversation:",
        *(history_lines or ["No previous conversation."]),
        f"Mentor question: {question[:4000]}",
    ])
    return StreamingResponse(
        Chatbot_stream(prompt),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.post("/signup")
def signup(data: SignupRequest):
    db = SessionLocal()
    try:
        if db.query(Student).filter(Student.roll_no == data.roll_no).first():
            raise HTTPException(status_code=400, detail="Roll number already registered")
        
        hashed_password = hash_password(data.password)
        new_student = Student(
            roll_no=data.roll_no,
            password=hashed_password,
            year=data.year
        )
        db.add(new_student)
        db.commit()
        return {"message": "Signup successful"}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/login")
def login(data: LoginRequest):
    db = SessionLocal()
    try:
        student = db.query(Student).filter(Student.roll_no == data.roll_no).first()
        if not student or not student.password or not verify_password(data.password, student.password):
            raise HTTPException(status_code=401, detail="Invalid roll number or password")
        return {
            "message": "Login successful",
            "roll_no": student.roll_no,
            "year": student.year
        }
    finally:
        db.close()

@app.post("/create-team")
def create_team(data: CreateTeamRequest):
    db = SessionLocal()
    try:
        if data.roll_no and db.query(TeamMember).filter(TeamMember.roll_no == data.roll_no).first():
            raise HTTPException(status_code=400, detail="You are already in a team. You cannot create another one.")

        code = generate_team_code()
        while db.query(Team).filter(Team.team_code == code).first():
            code = generate_team_code()

        new_team = Team(
            team_name=data.team_name,
            team_code=code,
            description=data.description,
            max_members=data.max_members
        )
        db.add(new_team)
        db.flush() # get new_team.id before commit to link member
        
        if data.roll_no:
            member = TeamMember(team_id=new_team.id, roll_no=data.roll_no)
            db.add(member)

        db.commit()
        db.refresh(new_team)
        all_members = db.query(TeamMember).filter(TeamMember.team_id == new_team.id).all()
        member_list = [m.roll_no for m in all_members]
        return {
            "message": "Team created successfully",
            "team_code": code,
            "team_name": new_team.team_name,
            "members": member_list
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/join-team")
def join_team(data: JoinTeamRequest):
    db = SessionLocal()
    try:
        if data.roll_no and db.query(TeamMember).filter(TeamMember.roll_no == data.roll_no).first():
            raise HTTPException(status_code=400, detail="You are already in a team. You cannot join multiple teams.")

        team = db.query(Team).filter(Team.team_code == data.team_code).first()
        if not team:
            raise HTTPException(status_code=404, detail="Invalid team code")
        
        current_members = db.query(TeamMember).filter(TeamMember.team_id == team.id).count()
        if current_members >= (team.max_members or 4):
            raise HTTPException(status_code=400, detail="Team is full")
        
        new_member = TeamMember(team_id=team.id, roll_no=data.roll_no)
        db.add(new_member)
        db.commit()

        # Fetch the entire new list of members so the UI can draw the Roster
        all_members = db.query(TeamMember).filter(TeamMember.team_id == team.id).all()
        member_list = [m.roll_no for m in all_members]

        return {
            "message": "Successfully joined the team", 
            "team_name": team.team_name,
            "team_code": team.team_code,
            "members": member_list
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.get("/get-student-team")
def get_student_team(roll_no: str):
    db = SessionLocal()
    try:
        member = db.query(TeamMember).filter(TeamMember.roll_no == roll_no).first()
        if not member:
            return {"has_team": False}
        
        team = db.query(Team).filter(Team.id == member.team_id).first()
        if not team:
            return {"has_team": False}
            
        all_members = db.query(TeamMember).filter(TeamMember.team_id == team.id).all()
        member_list = [m.roll_no for m in all_members]
        
        return {
            "has_team": True,
            "team_name": team.team_name,
            "team_code": team.team_code,
            "members": member_list
        }
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/leave-team")
def leave_team(data: LeaveTeamRequest):
    db = SessionLocal()
    try:
        member = db.query(TeamMember).filter(TeamMember.roll_no == data.roll_no).first()
        if not member:
            raise HTTPException(status_code=400, detail="You are not currently in a team.")
        
        team_id = member.team_id
        db.delete(member)
        db.commit()
        
        # Clean up empty teams
        remaining_members = db.query(TeamMember).filter(TeamMember.team_id == team_id).count()
        if remaining_members == 0:
            team = db.query(Team).filter(Team.id == team_id).first()
            if team:
                db.delete(team)
                db.commit()
                
        return {"message": "Successfully left the team"}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/submit-project")
def submit_project(data: ProjectSubmission):
    db = SessionLocal()
    try:
        # Find if the user is in a team
        member = db.query(TeamMember).filter(TeamMember.roll_no == data.roll_no).first()
        if not member:
            raise HTTPException(status_code=400, detail="You must join a team to submit a project")
            
        team = db.query(Team).filter(Team.id == member.team_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        student = db.query(Student).filter(Student.roll_no == data.roll_no).first()
        year = student.year if student else (team.year or "")

        new_project = Project(
            year=year,
            group_no=data.group_no,
            project_name=data.project_name,
            project_abstract=data.project_abstract,
            team_name=team.team_name
        )
        if engine.dialect.name == "postgresql":
            text = f"{data.project_name}. {data.project_abstract}".strip()
            new_project.embedding = CloudflareEmbeddingClient().embed(text)
        db.add(new_project)
        db.commit()
        db.refresh(new_project)
        return {"message": "Project submitted successfully!"}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/check-plagiarism")
async def check_plagiarism(
    file: Annotated[UploadFile | None, File()] = None,
    title: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
):
    try:
        file_bytes = await file.read(MAX_PLAGIARISM_UPLOAD_BYTES + 1) if file else b""
        if len(file_bytes) > MAX_PLAGIARISM_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="The uploaded file must be 20 MB or smaller.")
        filename = (file.filename or "") if file else ""
        result = await run_in_threadpool(
            run_plagiarism_check, title, description, file_bytes, filename
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except DocumentValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except DocumentExtractionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except DocumentLimitError as e:
        raise HTTPException(status_code=413, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 - translate document/parser failures to an API response
        logger.exception("Unexpected failure while processing plagiarism upload")
        raise HTTPException(
            status_code=500,
            detail="The uploaded document could not be processed. Check the file and try again.",
        ) from e

# ── Mentor Endpoints ──────────────────────────────────────────────

@app.post("/mentor/signup")
def mentor_signup(data: MentorSignupRequest):
    db = SessionLocal()
    try:
        username = data.username.strip()
        if db.query(Mentor).filter(func.lower(Mentor.username) == username.lower()).first():
            raise HTTPException(status_code=400, detail="Username already registered")

        hashed_password = hash_password(data.password)
        new_mentor = Mentor(
            username=username,
            password=hashed_password
        )
        db.add(new_mentor)
        db.commit()
        return {"message": "Mentor account created successfully"}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/mentor/login")
def mentor_login(data: MentorLoginRequest):
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == data.username.strip().lower()).first()
        if not mentor or not mentor.password or not verify_password(data.password, mentor.password):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return {
            "message": "Login successful",
            "username": mentor.username,
            "role": "mentor"
        }
    finally:
        db.close()

@app.get("/api/projects")
def list_projects():
    db = SessionLocal()
    try:
        projects = db.query(Project).all()
        return [
            {
                "id": p.id,
                "year": p.year,
                "group_no": p.group_no,
                "project_name": p.project_name,
                "project_abstract": p.project_abstract,
                "team": p.team_name
            }
            for p in projects
        ]
    finally:
        db.close()

@app.get("/api/students")
def get_students() -> list[dict[str, str | int | None]]:
    db = SessionLocal()
    try:
        students: list[Student] = db.query(Student).all()
        result: list[dict[str, str | int | None]] = []
        for s in students:
            member = db.query(TeamMember).filter(TeamMember.roll_no == s.roll_no).first()
            team_name = "No Team"
            project_name = "No Project"
            if member:
                team = db.query(Team).filter(Team.id == member.team_id).first()
                if team:
                    team_name = team.team_name
                    proj = db.query(Project).filter(Project.team_name == team.team_name).first()
                    if proj:
                        project_name = proj.project_name
            
            result.append({
                "roll_no": s.roll_no,
                "year": s.year,
                "team_name": team_name,
                "project_name": project_name,
                "submissions": "1 / 1" if project_name != "No Project" else "0 / 1"
            })
        return result
    finally:
        db.close()


@app.post("/mentor/students/import")
async def import_mentor_students(
    mentor_user: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Upload an .xlsx Excel file.")
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="The Excel file must be 5 MB or smaller.")

    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == mentor_user.strip().lower()).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        try:
            students = parse_mentor_roster(content, mentor.username)
        except (ValueError, InvalidFileException, BadZipFile) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        added = 0
        updated = 0
        for row in students:
            if row["prn"]:
                existing = db.query(MentorStudent).filter(MentorStudent.prn == row["prn"]).first()
            else:
                existing = db.query(MentorStudent).filter(
                    MentorStudent.mentor_key == row["mentor_key"],
                    func.lower(MentorStudent.student_name) == row["student_name"].lower(),
                ).first()
            if existing:
                updated += 1
            else:
                existing = MentorStudent()
                db.add(existing)
                added += 1
            for field, value in row.items():
                setattr(existing, field, value)
        db.commit()
        return {"added": added, "updated": updated, "total": len(students)}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise
    finally:
        db.close()


@app.get("/mentor/students")
def get_mentor_students(mentor_user: str) -> list[dict[str, str | int]]:
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == mentor_user.strip().lower()).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        roster: list[MentorStudent] = db.query(MentorStudent).filter(
            MentorStudent.mentor_key == mentor_key(mentor.username)
        ).order_by(MentorStudent.student_name).all()
        result: list[dict[str, str | int]] = []
        for entry in roster:
            team_name = entry.group_name or "No Group"
            project_name = entry.project_name or "No Project"
            if entry.prn:
                member = db.query(TeamMember).filter(TeamMember.roll_no == entry.prn).first()
                if member:
                    team = db.query(Team).filter(Team.id == member.team_id).first()
                    if team:
                        team_name = team.team_name or "No Group"
                        project = db.query(Project).filter(Project.team_name == team.team_name).first()
                        if project and not entry.project_name:
                            project_name = project.project_name or "No Project"
            result.append({
                "id": entry.id,
                "student_name": entry.student_name,
                "prn": entry.prn or "",
                "mentor_name": entry.mentor_name,
                "year": entry.year or "",
                "group_number": entry.group_name or "",
                "team_name": team_name,
                "project_name": project_name,
                "submissions": "1 / 1" if project_name != "No Project" else "0 / 1",
            })
        return result
    finally:
        db.close()


@app.post("/team-invitations", status_code=201)
def create_team_invitation(data: TeamInviteRequest):
    db = SessionLocal()
    try:
        inviter_roll = data.inviter_roll_no.strip()
        invitee_input = data.invitee_roll_no.strip()
        inviter_member = db.query(TeamMember).filter(TeamMember.roll_no == inviter_roll).first()
        if not inviter_member:
            raise HTTPException(status_code=400, detail="You must be in a team before inviting members.")
        team = db.query(Team).filter(Team.id == inviter_member.team_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")
        invitee = db.query(Student).filter(func.lower(Student.roll_no) == invitee_input.lower()).first()
        if not invitee:
            raise HTTPException(status_code=404, detail="No registered student has that PRN or roll number.")
        if invitee.roll_no.lower() == inviter_roll.lower():
            raise HTTPException(status_code=400, detail="You cannot invite yourself.")
        if db.query(TeamMember).filter(TeamMember.roll_no == invitee.roll_no).first():
            raise HTTPException(status_code=409, detail="This student is already in a team.")
        existing = db.query(TeamInvitation).filter(
            TeamInvitation.team_id == team.id,
            func.lower(TeamInvitation.invitee_roll_no) == invitee.roll_no.lower(),
            TeamInvitation.status == "pending",
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="This student already has a pending invitation from your team.")
        member_count = db.query(TeamMember).filter(TeamMember.team_id == team.id).count()
        pending_count = db.query(TeamInvitation).filter(
            TeamInvitation.team_id == team.id, TeamInvitation.status == "pending"
        ).count()
        if member_count + pending_count >= (team.max_members or 4):
            raise HTTPException(status_code=409, detail="All remaining team slots already have pending invitations.")
        invitation = TeamInvitation(
            team_id=team.id,
            inviter_roll_no=inviter_roll,
            invitee_roll_no=invitee.roll_no,
            status="pending",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        db.add(invitation)
        db.commit()
        db.refresh(invitation)
        return {"id": invitation.id, "message": f"Invitation sent to {invitee.roll_no}."}
    finally:
        db.close()


@app.get("/team-invitations")
def get_team_invitations(roll_no: str):
    db = SessionLocal()
    try:
        invitations = db.query(TeamInvitation).filter(
            func.lower(TeamInvitation.invitee_roll_no) == roll_no.strip().lower(),
            TeamInvitation.status == "pending",
        ).order_by(TeamInvitation.created_at.desc(), TeamInvitation.id.desc()).all()
        result = []
        for invitation in invitations:
            team = db.query(Team).filter(Team.id == invitation.team_id).first()
            if team:
                result.append({
                    "id": invitation.id,
                    "team_name": team.team_name,
                    "team_code": team.team_code,
                    "inviter_roll_no": invitation.inviter_roll_no,
                    "created_at": invitation.created_at,
                })
        return result
    finally:
        db.close()


@app.patch("/team-invitations/{invitation_id}")
def respond_to_team_invitation(invitation_id: int, data: TeamInviteResponse):
    action = data.action.strip().lower()
    if action not in {"accept", "decline"}:
        raise HTTPException(status_code=400, detail="Invitation action must be accept or decline.")
    db = SessionLocal()
    try:
        invitation = db.query(TeamInvitation).filter(
            TeamInvitation.id == invitation_id,
            func.lower(TeamInvitation.invitee_roll_no) == data.roll_no.strip().lower(),
            TeamInvitation.status == "pending",
        ).first()
        if not invitation:
            raise HTTPException(status_code=404, detail="Invitation is no longer available.")
        if action == "decline":
            invitation.status = "declined"
            invitation.responded_at = datetime.now().isoformat(timespec="seconds")
            db.commit()
            return {"message": "Invitation declined.", "status": "declined"}
        if db.query(TeamMember).filter(TeamMember.roll_no == invitation.invitee_roll_no).first():
            raise HTTPException(status_code=409, detail="You are already in a team.")
        team = db.query(Team).filter(Team.id == invitation.team_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="This team no longer exists.")
        member_count = db.query(TeamMember).filter(TeamMember.team_id == team.id).count()
        if member_count >= (team.max_members or 4):
            raise HTTPException(status_code=409, detail="This team is already full.")
        db.add(TeamMember(team_id=team.id, roll_no=invitation.invitee_roll_no))
        invitation.status = "accepted"
        invitation.responded_at = datetime.now().isoformat(timespec="seconds")
        other_invitations = db.query(TeamInvitation).filter(
            func.lower(TeamInvitation.invitee_roll_no) == invitation.invitee_roll_no.lower(),
            TeamInvitation.status == "pending",
            TeamInvitation.id != invitation.id,
        ).all()
        for other in other_invitations:
            other.status = "declined"
            other.responded_at = invitation.responded_at
        db.commit()
        members = db.query(TeamMember).filter(TeamMember.team_id == team.id).order_by(TeamMember.id).all()
        return {
            "message": f"You joined {team.team_name}.",
            "status": "accepted",
            "team_name": team.team_name,
            "team_code": team.team_code,
            "members": [member.roll_no for member in members],
        }
    finally:
        db.close()


def review_payload(review: MentorReview):
    return {
        "id": review.id,
        "group_number": review.group_name,
        "review_type": review.review_type,
        "review_date": review.review_date,
        "review_time": review.review_time,
        "notes": review.notes or "",
        "status": review.status,
        "created_at": review.created_at,
        "completed_at": review.completed_at or "",
    }


@app.get("/mentor/dashboard")
def get_mentor_dashboard(mentor_user: str):
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == mentor_user.strip().lower()).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        key = mentor_key(mentor.username)
        students = db.query(MentorStudent).filter(MentorStudent.mentor_key == key).all()
        reviews = db.query(MentorReview).filter(MentorReview.mentor_key == key).order_by(
            MentorReview.created_at.desc(), MentorReview.id.desc()
        ).all()
        projects = {
            student.project_name.strip().lower()
            for student in students
            if student.project_name and student.project_name.strip().lower() != "no project"
        }
        return {
            "assigned_students": len(students),
            "active_projects": len(projects),
            "pending_reviews": sum(review.status == "scheduled" for review in reviews),
            "reviews_done": sum(review.status == "completed" for review in reviews),
            "reviews": [review_payload(review) for review in reviews[:20]],
        }
    finally:
        db.close()


@app.post("/mentor/reviews", status_code=201)
def create_mentor_review(data: MentorReviewCreate):
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == data.mentor_user.strip().lower()).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        group_number = data.group_number.strip()
        group_exists = db.query(MentorStudent).filter(
            MentorStudent.mentor_key == mentor_key(mentor.username),
            func.lower(MentorStudent.group_name) == group_number.lower(),
        ).first()
        if not group_number or not group_exists:
            raise HTTPException(status_code=400, detail="Select a group assigned to this mentor.")
        review_type = data.review_type.strip()
        if review_type not in {"Progress Review-1", "Progress Review-2", "Final Presentation"}:
            raise HTTPException(status_code=400, detail="Select a valid review type.")
        try:
            scheduled = datetime.fromisoformat(f"{data.review_date}T{data.review_time}")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Enter a valid review date and time.") from exc
        if scheduled < datetime.now():
            raise HTTPException(status_code=400, detail="Review time must be in the future.")
        review = MentorReview(
            mentor_name=mentor.username,
            mentor_key=mentor_key(mentor.username),
            group_name=group_number,
            review_type=review_type,
            review_date=data.review_date,
            review_time=data.review_time,
            notes=data.notes.strip() or None,
            status="scheduled",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        db.add(review)
        db.commit()
        db.refresh(review)
        return review_payload(review)
    finally:
        db.close()


@app.patch("/mentor/reviews/{review_id}")
def update_mentor_review_status(review_id: int, data: MentorReviewStatus):
    if data.status not in {"completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Review status must be completed or cancelled.")
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == data.mentor_user.strip().lower()).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        review = db.query(MentorReview).filter(
            MentorReview.id == review_id,
            MentorReview.mentor_key == mentor_key(mentor.username),
        ).first()
        if not review:
            raise HTTPException(status_code=404, detail="Review not found.")
        review.status = data.status
        review.completed_at = datetime.now().isoformat(timespec="seconds") if data.status == "completed" else None
        db.commit()
        return review_payload(review)
    finally:
        db.close()


@app.post("/mentor/students", status_code=201)
def add_mentor_student(data: MentorStudentCreate):
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == data.mentor_user.strip().lower()).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        name = " ".join(data.student_name.split())
        if not name:
            raise HTTPException(status_code=400, detail="Student name is required.")
        prn = data.prn.strip()
        existing = db.query(MentorStudent).filter(func.lower(MentorStudent.prn) == prn.lower()).first() if prn else None
        if existing:
            if not data.transfer_existing:
                raise HTTPException(status_code=409, detail={
                    "code": "PRN_ASSIGNED",
                    "student_name": existing.student_name,
                    "mentor_name": existing.mentor_name,
                    "group_number": existing.group_name or "",
                })
            previous_mentor = existing.mentor_name
            existing.mentor_name = mentor.username
            existing.mentor_key = mentor_key(mentor.username)
            existing.student_name = name
            existing.prn = prn
            existing.group_name = data.group_number.strip() or None
            # Blank optional fields in the add form should not erase imported details.
            existing.project_name = data.project_name.strip() or existing.project_name
            existing.year = data.year.strip() or existing.year
            db.commit()
            return JSONResponse(status_code=200, content={
                "id": existing.id,
                "transferred": True,
                "message": "Student moved to mentor roster.",
                "previous_mentor": previous_mentor,
            })
        entry = MentorStudent(
            mentor_name=mentor.username,
            mentor_key=mentor_key(mentor.username),
            student_name=name,
            prn=prn or None,
            group_name=data.group_number.strip() or None,
            project_name=data.project_name.strip() or None,
            year=data.year.strip() or None,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return {"id": entry.id, "message": "Student added to mentor roster."}
    finally:
        db.close()


@app.put("/mentor/students/{roster_id}")
def update_mentor_student(roster_id: int, data: MentorStudentUpdate):
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == data.mentor_user.strip().lower()).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        entry = db.query(MentorStudent).filter(
            MentorStudent.id == roster_id,
            MentorStudent.mentor_key == mentor_key(mentor.username),
        ).first()
        if not entry:
            raise HTTPException(status_code=404, detail="Student is not in your roster.")
        name = " ".join(data.student_name.split())
        if not name:
            raise HTTPException(status_code=400, detail="Student name is required.")
        prn = data.prn.strip()
        if prn and db.query(MentorStudent).filter(
            MentorStudent.prn == prn,
            MentorStudent.id != roster_id,
        ).first():
            raise HTTPException(status_code=409, detail="Another student already has this PRN.")
        entry.student_name = name
        entry.prn = prn or None
        entry.group_name = data.group_number.strip() or None
        entry.project_name = data.project_name.strip() or None
        entry.year = data.year.strip() or None
        db.commit()
        return {"message": "Student updated."}
    finally:
        db.close()


@app.delete("/mentor/students/{roster_id}")
def delete_mentor_student(roster_id: int, mentor_user: str):
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == mentor_user.strip().lower()).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        entry = db.query(MentorStudent).filter(
            MentorStudent.id == roster_id,
            MentorStudent.mentor_key == mentor_key(mentor.username),
        ).first()
        if not entry:
            raise HTTPException(status_code=404, detail="Student is not in your roster.")
        db.delete(entry)
        db.commit()
        return {"message": "Student removed from mentor roster."}
    finally:
        db.close()
