from contextlib import asynccontextmanager
import logging
import os
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zipfile import BadZipFile

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from openpyxl.utils.exceptions import InvalidFileException
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from clerk_backend_api import Clerk

from axiom_ai import Chatbot_stream
from database import SessionLocal, enable_pgvector, engine, migrate_database
from clerk_auth import require_clerk_user_id, validate_production_clerk_config
from mentor_roster import mentor_key, parse_mentor_roster
from models import Base, Mentor, MentorReview, MentorStudent, Project, Student, Team, TeamInvitation, TeamMember
from nlp.checker import run_plagiarism_check
from group_connect import create_router
from nlp.extractor import DocumentExtractionError, DocumentLimitError, DocumentValidationError
from utils import generate_team_code
from embeddings import CloudflareEmbeddingClient


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_production_clerk_config()
    # Create all runtime tables in PostgreSQL only after pgvector is enabled.
    enable_pgvector()
    Base.metadata.create_all(bind=engine)
    migrate_database()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(create_router(lambda: SessionLocal()))
logger = logging.getLogger(__name__)


class ClerkProfileLinkRequest(BaseModel):
    role: Literal["student", "mentor"]
    roll_no: str | None = None
    year: str | None = None
    mentor_name: str | None = None


@app.get("/api/config")
def public_config():
    """Expose browser-safe configuration only; secret keys stay server-side."""
    publishable_key = os.getenv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "").strip()
    if not publishable_key:
        raise HTTPException(
            status_code=503,
            detail="Clerk publishable key is not configured on the server.",
        )
    return {"clerk_publishable_key": publishable_key}


def resolve_profile_for_clerk_user_id(clerk_user_id: str) -> dict[str, str | None]:
    """Load the one PostgreSQL profile linked to a verified Clerk subject."""
    db = SessionLocal()
    try:
        student = db.query(Student).filter(Student.clerk_user_id == clerk_user_id).first()
        mentor = db.query(Mentor).filter(Mentor.clerk_user_id == clerk_user_id).first()
        if student and mentor:
            raise HTTPException(status_code=409, detail="Clerk user is linked to multiple application profiles.")
        if student:
            if not student.roll_no:
                raise HTTPException(status_code=409, detail="Linked student profile has no roll number.")
            return {"role": "student", "identifier": student.roll_no, "year": student.year}
        if mentor:
            if not mentor.username:
                raise HTTPException(status_code=409, detail="Linked mentor profile has no username.")
            return {"role": "mentor", "identifier": mentor.username, "year": None}
        raise HTTPException(status_code=403, detail="This Clerk user has no linked application profile.")
    except HTTPException:
        raise
    except SQLAlchemyError as error:
        logger.exception("Failed to resolve the authenticated Clerk profile")
        raise HTTPException(status_code=503, detail="Application profile lookup is unavailable.") from error
    finally:
        db.close()


@app.middleware("http")
async def require_clerk_for_application_routes(request: Request, call_next):
    """Fail closed by default; allow browser config/docs and retire password auth routes."""
    path = request.url.path
    retired_auth_paths = {"/signup", "/login", "/mentor/signup", "/mentor/login"}
    if request.method == "OPTIONS" or path in {"/api/config", "/openapi.json", "/docs", "/redoc"}:
        return await call_next(request)
    if path in retired_auth_paths:
        return JSONResponse(
            status_code=410,
            content={"detail": "Password-based authentication is retired. Use Clerk sign-in or sign-up."},
        )

    try:
        clerk_user_id = require_clerk_user_id(request)
        request.state.clerk_user_id = clerk_user_id
        if path != "/api/profile/link":
            request.state.profile = resolve_profile_for_clerk_user_id(clerk_user_id)
    except HTTPException as error:
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": error.detail},
            headers=error.headers,
        )
    return await call_next(request)


def require_profile_role(request: Request, role: str) -> dict[str, str | None]:
    profile = getattr(request.state, "profile", None)
    if profile is None:
        raise HTTPException(status_code=401, detail="A linked Clerk profile is required.")
    if profile["role"] != role:
        raise HTTPException(status_code=403, detail=f"A {role} account is required for this action.")
    return profile


@app.get("/api/me")
def get_current_profile(request: Request):
    """Return the application profile for a valid Clerk session token."""
    return request.state.profile


@app.delete("/api/account")
def delete_current_account(request: Request):
    """Remove the caller's app profile and Clerk identity, preserving academic data."""
    clerk_user_id = request.state.clerk_user_id
    profile = request.state.profile
    db = SessionLocal()
    try:
        if profile["role"] == "student":
            account = db.query(Student).filter(Student.clerk_user_id == clerk_user_id).first()
        else:
            account = db.query(Mentor).filter(Mentor.clerk_user_id == clerk_user_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Your application profile no longer exists.")

        secret_key = os.getenv("CLERK_SECRET_KEY", "").strip()
        if not secret_key:
            raise HTTPException(status_code=503, detail="Clerk account deletion is not configured.")

        # Remove credentials first. Team, roster, invitation, review, and project
        # rows intentionally remain because they are not login-profile records.
        Clerk(bearer_auth=secret_key).users.delete(user_id=clerk_user_id, timeout_ms=10_000)
        db.delete(account)
        db.commit()
        return {"message": "Account deleted.", "role": profile["role"]}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as error:
        db.rollback()
        logger.exception("Clerk user was deleted but the application profile could not be removed")
        raise HTTPException(status_code=500, detail="Your Clerk account was deleted, but the application profile could not be removed.") from error
    except Exception as error:  # Clerk SDK errors are intentionally not exposed to the browser.
        logger.exception("Could not delete Clerk account")
        raise HTTPException(status_code=503, detail="Could not delete the Clerk account. Please try again.") from error
    finally:
        db.close()


@app.post("/api/profile/link")
def link_clerk_profile(data: ClerkProfileLinkRequest, request: Request):
    """Create a PostgreSQL profile bound to the verified Clerk session subject."""
    clerk_user_id = request.state.clerk_user_id
    db = SessionLocal()
    try:
        linked_student = db.query(Student).filter(Student.clerk_user_id == clerk_user_id).first()
        linked_mentor = db.query(Mentor).filter(Mentor.clerk_user_id == clerk_user_id).first()

        if data.role == "student":
            roll_no = (data.roll_no or "").strip()
            if not roll_no:
                raise HTTPException(status_code=422, detail="Roll number is required.")
            if linked_mentor:
                raise HTTPException(status_code=409, detail="This Clerk user is already linked as a mentor.")
            if linked_student:
                if linked_student.roll_no != roll_no:
                    raise HTTPException(status_code=409, detail="This Clerk user is already linked to another roll number.")
                if data.year is not None:
                    linked_student.year = data.year.strip()
                db.commit()
                return {
                    "role": "student",
                    "clerk_user_id": clerk_user_id,
                    "roll_no": linked_student.roll_no,
                    "year": linked_student.year,
                }

            existing_student = db.query(Student).filter(
                func.lower(Student.roll_no) == roll_no.lower()
            ).first()
            if existing_student:
                message = "This roll number already has a PostgreSQL profile. Existing accounts must be linked manually."
                if existing_student.clerk_user_id:
                    message = "This roll number is already linked to another Clerk user."
                raise HTTPException(status_code=409, detail=message)

            profile = Student(
                roll_no=roll_no,
                year=(data.year or "").strip() or None,
                clerk_user_id=clerk_user_id,
            )
            db.add(profile)
            db.commit()
            return {
                "role": "student",
                "clerk_user_id": clerk_user_id,
                "roll_no": profile.roll_no,
                "year": profile.year,
            }

        mentor_name = (data.mentor_name or "").strip()
        if not mentor_name:
            raise HTTPException(status_code=422, detail="Mentor name is required.")
        if linked_student:
            raise HTTPException(status_code=409, detail="This Clerk user is already linked as a student.")
        if linked_mentor:
            if (linked_mentor.username or "").casefold() != mentor_name.casefold():
                raise HTTPException(status_code=409, detail="This Clerk user is already linked to another mentor name.")
            db.commit()
            return {
                "role": "mentor",
                "clerk_user_id": clerk_user_id,
                "mentor_name": linked_mentor.username,
            }

        existing_mentor = db.query(Mentor).filter(
            func.lower(Mentor.username) == mentor_name.lower()
        ).first()
        if existing_mentor:
            message = "This mentor profile already exists in PostgreSQL. Existing accounts must be linked manually."
            if existing_mentor.clerk_user_id:
                message = "This mentor name is already linked to another Clerk user."
            raise HTTPException(status_code=409, detail=message)

        profile = Mentor(username=mentor_name, clerk_user_id=clerk_user_id)
        db.add(profile)
        db.commit()
        return {
            "role": "mentor",
            "clerk_user_id": clerk_user_id,
            "mentor_name": profile.username,
        }
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This profile or Clerk user is already linked.") from error
    except SQLAlchemyError as error:
        db.rollback()
        logger.exception("Failed to link a Clerk profile to PostgreSQL")
        raise HTTPException(status_code=500, detail="Could not save the application profile.") from error
    finally:
        db.close()

MAX_PLAGIARISM_UPLOAD_BYTES = 20 * 1024 * 1024

# Middleware
def _is_production_environment() -> bool:
    return os.getenv("APP_ENV", "").strip().lower() == "production" or os.getenv("RENDER", "").lower() == "true"


def _configured_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if not raw:
        if _is_production_environment():
            raise RuntimeError("CORS_ALLOWED_ORIGINS must list the deployed HTTPS frontend origin(s).")
        return ["http://127.0.0.1:5500", "http://localhost:5500"]

    origins = [value.strip().rstrip("/") for value in raw.split(",") if value.strip()]
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            raise RuntimeError("CORS_ALLOWED_ORIGINS must contain only exact origins, without paths or wildcards.")
        if _is_production_environment() and parsed.scheme != "https":
            raise RuntimeError("Production CORS_ALLOWED_ORIGINS entries must use HTTPS.")
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_configured_origins(),
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
    # Middleware requires a verified, linked student or mentor profile.
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
async def mentor_axiom_stream(data: MentorAxiomRequest, request: Request):
    require_profile_role(request, "mentor")
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
def signup():
    raise HTTPException(status_code=410, detail="Password-based sign-up is retired. Use Clerk.")

@app.post("/login")
def login():
    raise HTTPException(status_code=410, detail="Password-based sign-in is retired. Use Clerk.")

@app.post("/create-team")
def create_team(data: CreateTeamRequest, request: Request):
    profile = require_profile_role(request, "student")
    roll_no = profile["identifier"]
    db = SessionLocal()
    try:
        if db.query(TeamMember).filter(TeamMember.roll_no == roll_no).first():
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
        
        member = TeamMember(team_id=new_team.id, roll_no=roll_no)
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
def join_team(data: JoinTeamRequest, request: Request):
    profile = require_profile_role(request, "student")
    roll_no = profile["identifier"]
    db = SessionLocal()
    try:
        if db.query(TeamMember).filter(TeamMember.roll_no == roll_no).first():
            raise HTTPException(status_code=400, detail="You are already in a team. You cannot join multiple teams.")

        team = db.query(Team).filter(Team.team_code == data.team_code).first()
        if not team:
            raise HTTPException(status_code=404, detail="Invalid team code")
        
        current_members = db.query(TeamMember).filter(TeamMember.team_id == team.id).count()
        if current_members >= (team.max_members or 4):
            raise HTTPException(status_code=400, detail="Team is full")
        
        new_member = TeamMember(team_id=team.id, roll_no=roll_no)
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
def get_student_team(request: Request, roll_no: str | None = None):
    roll_no = require_profile_role(request, "student")["identifier"]
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
def leave_team(data: LeaveTeamRequest, request: Request):
    roll_no = require_profile_role(request, "student")["identifier"]
    db = SessionLocal()
    try:
        member = db.query(TeamMember).filter(TeamMember.roll_no == roll_no).first()
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
def submit_project(data: ProjectSubmission, request: Request):
    roll_no = require_profile_role(request, "student")["identifier"]
    db = SessionLocal()
    try:
        # Find if the user is in a team
        member = db.query(TeamMember).filter(TeamMember.roll_no == roll_no).first()
        if not member:
            raise HTTPException(status_code=400, detail="You must join a team to submit a project")
            
        team = db.query(Team).filter(Team.id == member.team_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        student = db.query(Student).filter(Student.roll_no == roll_no).first()
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
def mentor_signup():
    raise HTTPException(status_code=410, detail="Password-based sign-up is retired. Use Clerk.")

@app.post("/mentor/login")
def mentor_login():
    raise HTTPException(status_code=410, detail="Password-based sign-in is retired. Use Clerk.")

@app.get("/api/projects")
def list_projects(request: Request):
    require_profile_role(request, "mentor")
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
def get_students(request: Request) -> list[dict[str, str | int | None]]:
    require_profile_role(request, "mentor")
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
    file: Annotated[UploadFile, File()],
    request: Request,
    mentor_user: Annotated[str | None, Form()] = None,
):
    mentor_user = require_profile_role(request, "mentor")["identifier"]
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
def get_mentor_students(request: Request, mentor_user: str | None = None) -> list[dict[str, str | int]]:
    mentor_user = require_profile_role(request, "mentor")["identifier"]
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
def create_team_invitation(data: TeamInviteRequest, request: Request):
    inviter_roll_no = require_profile_role(request, "student")["identifier"]
    db = SessionLocal()
    try:
        inviter_roll = inviter_roll_no
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
def get_team_invitations(request: Request, roll_no: str | None = None):
    roll_no = require_profile_role(request, "student")["identifier"]
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
def respond_to_team_invitation(invitation_id: int, data: TeamInviteResponse, request: Request):
    roll_no = require_profile_role(request, "student")["identifier"]
    action = data.action.strip().lower()
    if action not in {"accept", "decline"}:
        raise HTTPException(status_code=400, detail="Invitation action must be accept or decline.")
    db = SessionLocal()
    try:
        invitation = db.query(TeamInvitation).filter(
            TeamInvitation.id == invitation_id,
            func.lower(TeamInvitation.invitee_roll_no) == roll_no.strip().lower(),
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
def get_mentor_dashboard(request: Request, mentor_user: str | None = None):
    mentor_user = require_profile_role(request, "mentor")["identifier"]
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
def create_mentor_review(data: MentorReviewCreate, request: Request):
    mentor_user = require_profile_role(request, "mentor")["identifier"]
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == mentor_user.strip().lower()).first()
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
def update_mentor_review_status(review_id: int, data: MentorReviewStatus, request: Request):
    mentor_user = require_profile_role(request, "mentor")["identifier"]
    if data.status not in {"completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Review status must be completed or cancelled.")
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == mentor_user.strip().lower()).first()
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
def add_mentor_student(data: MentorStudentCreate, request: Request):
    mentor_user = require_profile_role(request, "mentor")["identifier"]
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == mentor_user.strip().lower()).first()
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
def update_mentor_student(roster_id: int, data: MentorStudentUpdate, request: Request):
    mentor_user = require_profile_role(request, "mentor")["identifier"]
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
def delete_mentor_student(roster_id: int, request: Request, mentor_user: str | None = None):
    mentor_user = require_profile_role(request, "mentor")["identifier"]
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
