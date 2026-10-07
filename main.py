from contextlib import asynccontextmanager
import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zipfile import BadZipFile

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, delete, func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from clerk_backend_api import Clerk

from axiom_ai import Chatbot_stream
from database import SessionLocal, enable_pgvector, engine, migrate_database
from clerk_auth import require_clerk_user_id, validate_production_clerk_config
from mentor_roster import mentor_key, parse_mentor_roster
from enrollment import redeem_student
from models import ApiRateLimitBucket, Base, EnrollmentCode, Mentor, MentorReview, MentorStudent, Project, Student, Team, TeamInvitation, TeamMember
from enrollment import code_hash
import secrets
from group_connect import create_router
from project_access import mentor_projects, project_summary, roster_for_project_owners
from nlp.extractor import DocumentExtractionError, DocumentLimitError, DocumentValidationError
from utils import generate_team_code
from embeddings import CloudflareEmbeddingClient


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_production_clerk_config()
    _trusted_proxy_networks()
    # Create all runtime tables in PostgreSQL only after pgvector is enabled.
    enable_pgvector()
    Base.metadata.create_all(bind=engine)
    migrate_database()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(create_router(lambda: SessionLocal()))
logger = logging.getLogger(__name__)

# Shared PostgreSQL limits apply across API workers. IP counters require configured trusted
# proxy ranges when the app sits behind a reverse proxy; untrusted X-Forwarded-For is ignored.
RATE_LIMITS = {
    ("/api/admin/enrollments", "POST"): (30, 60, 120),
    ("/api/profile/link", "POST"): (5, 3600, 100),
    ("/api/projects/{project_id}/assign", "PATCH"): (10, 3600, 100),
    ("/chat-stream", "GET"): (8, 60, 120),
    ("/mentor/axiom-stream", "POST"): (5, 60, 60),
    ("/check-plagiarism", "POST"): (3, 60, 30),
    ("/submit-project", "POST"): (3, 60, 30),
    ("/team-invitations", "POST"): (10, 60, 120),
    ("/join-team", "POST"): (5, 60, 100),
    ("/mentor/students/import", "POST"): (5, 3600, 50),
    ("/mentor/students", "POST"): (20, 3600, 200),
}
_plagiarism_semaphore = asyncio.Semaphore(1)
_last_rate_cleanup = 0


def _trusted_proxy_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    networks = []
    for value in os.getenv("TRUSTED_PROXY_IPS", "").split(","):
        value = value.strip()
        if value:
            try:
                networks.append(ipaddress.ip_network(value, strict=False))
            except ValueError as error:
                raise RuntimeError("TRUSTED_PROXY_IPS must contain IP addresses or CIDR ranges.") from error
    return networks


def _request_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    networks = _trusted_proxy_networks()
    if not any(peer_address in network for network in networks):
        return peer_address.compressed

    forwarded = request.headers.get("x-forwarded-for", "")
    chain = []
    for value in forwarded.split(","):
        try:
            chain.append(ipaddress.ip_address(value.strip()))
        except ValueError:
            return peer_address.compressed
    for address in reversed(chain):
        if not any(address in network for network in networks):
            return address.compressed
    return peer_address.compressed


def _rate_bucket_key(scope: str, identity: str, method: str, path: str) -> str:
    secret = (os.getenv("RATE_LIMIT_HASH_KEY") or os.getenv("CLERK_SECRET_KEY", "")).encode()
    value = f"{scope}:{identity}:{method.upper()}:{path}".encode()
    return hmac.new(secret, value, hashlib.sha256).hexdigest()


def rate_limit_retry_after(user_id: str, client_ip: str, method: str, path: str) -> int | None:
    normalized_path = path
    if path.startswith("/api/projects/") and path.endswith("/assign"):
        normalized_path = "/api/projects/{project_id}/assign"
    configured = RATE_LIMITS.get((normalized_path, method.upper()))
    if not configured:
        return None
    user_maximum, window, ip_maximum = configured
    now = int(time.time())
    window_start = now // window * window
    expires_at = window_start + window + 86400
    buckets = (
        (_rate_bucket_key("user", user_id, method, normalized_path), user_maximum),
        (_rate_bucket_key("ip", client_ip, method, normalized_path), ip_maximum),
    )
    retry_after = None
    global _last_rate_cleanup
    with SessionLocal() as db:
        for key, maximum in buckets:
            statement = pg_insert(ApiRateLimitBucket).values(
                bucket_key=key,
                window_start=window_start,
                request_count=1,
                expires_at=expires_at,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[ApiRateLimitBucket.bucket_key],
                set_={
                    "window_start": statement.excluded.window_start,
                    "request_count": case(
                        (
                            ApiRateLimitBucket.window_start == window_start,
                            ApiRateLimitBucket.request_count + 1,
                        ),
                        else_=1,
                    ),
                    "expires_at": statement.excluded.expires_at,
                },
            ).returning(ApiRateLimitBucket.request_count)
            count = db.execute(statement).scalar_one()
            if count > maximum:
                remaining = max(1, window_start + window - now)
                retry_after = max(retry_after or 0, remaining)
        if now - _last_rate_cleanup >= 600:
            db.execute(delete(ApiRateLimitBucket).where(ApiRateLimitBucket.expires_at < now))
            _last_rate_cleanup = now
        db.commit()
    return retry_after


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClerkProfileLinkRequest(StrictRequest):
    enrollment_code: str | None = Field(default=None, min_length=1, max_length=128)
    role: Literal["student", "mentor"]
    roll_no: str | None = Field(default=None, min_length=1, max_length=64)
    year: str | None = Field(default=None, max_length=64)
    mentor_name: str | None = Field(default=None, min_length=1, max_length=120)


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
        logger.error("Authenticated profile lookup failed (%s)", type(error).__name__)
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
        if path.startswith("/api/admin/"):
            require_enrollment_admin(request)
        elif path != "/api/profile/link":
            request.state.profile = resolve_profile_for_clerk_user_id(clerk_user_id)
        retry_after = rate_limit_retry_after(
            clerk_user_id, _request_client_ip(request), request.method, path
        )
        if retry_after is not None:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please wait before trying again."},
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException as error:
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": error.detail},
            headers=error.headers,
        )
    except SQLAlchemyError as error:
        logger.error("Shared rate limit check failed (%s)", type(error).__name__)
        return JSONResponse(
            status_code=503,
            content={"detail": "Abuse protection is temporarily unavailable. Please retry."},
        )
    response = await call_next(request)
    if path.startswith("/api/admin/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def require_profile_role(request: Request, role: str) -> dict[str, str | None]:
    profile = getattr(request.state, "profile", None)
    if profile is None:
        raise HTTPException(status_code=401, detail="A linked Clerk profile is required.")
    if profile["role"] != role:
        raise HTTPException(status_code=403, detail=f"A {role} account is required for this action.")
    return profile


def _team_project_for_student(db, roll_no: str) -> Project | None:
    member = db.query(TeamMember).filter(
        func.lower(TeamMember.roll_no) == roll_no.strip().lower()
    ).first()
    if not member:
        return None
    return db.query(Project).filter(Project.team_id == member.team_id).first()


def _project_available_to_mentor(db, roll_no: str, mentor_id: int) -> Project | None:
    project = _team_project_for_student(db, roll_no)
    if project and project.assigned_mentor_id not in (None, mentor_id):
        raise HTTPException(
            status_code=409,
            detail="This student's team project is assigned to another mentor.",
        )
    return project


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
        logger.error("Clerk user was deleted but application profile removal failed (%s)", type(error).__name__)
        raise HTTPException(status_code=500, detail="Your Clerk account was deleted, but the application profile could not be removed.") from error
    except Exception as error:  # Clerk SDK errors are intentionally not exposed to the browser.
        logger.error("Could not delete Clerk account (%s)", type(error).__name__)
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
                db.commit()
                return {
                    "role": "student",
                    "roll_no": linked_student.roll_no,
                    "year": linked_student.year,
                }

            if not data.enrollment_code or not data.year:
                raise HTTPException(status_code=422, detail="Enrollment code and year are required.")
            profile = redeem_student(db, clerk_user_id, roll_no, data.year, data.enrollment_code)
            db.commit()
            return {
                "role": "student",
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
        logger.error("Clerk profile link persistence failed (%s)", type(error).__name__)
        raise HTTPException(status_code=500, detail="Could not save the application profile.") from error
    finally:
        db.close()

MAX_PLAGIARISM_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PLAGIARISM_RUNTIME_SECONDS = 90

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
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment
                or "*" in origin or parsed.username or parsed.password):
            raise RuntimeError("CORS_ALLOWED_ORIGINS must contain only exact origins, without paths or wildcards.")
        if _is_production_environment() and parsed.scheme != "https":
            raise RuntimeError("Production CORS_ALLOWED_ORIGINS entries must use HTTPS.")
    return origins


async def run_plagiarism_check_with_deadline(
    title: str, description: str, file_bytes: bytes, filename: str
) -> dict[str, object]:
    """Run CPU/provider work in a child process that can be killed at the deadline."""
    with tempfile.TemporaryDirectory(prefix="project-guard-plagiarism-") as temp_dir:
        temp_path = Path(temp_dir)
        upload_path = temp_path / "upload.bin"
        upload_path.write_bytes(file_bytes)
        request_path = temp_path / "request.json"
        request_path.write_text(
            json.dumps({
                "title": title,
                "description": description,
                "filename": filename,
                "file_path": str(upload_path),
            }),
            encoding="utf-8",
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "nlp.plagiarism_worker",
            str(request_path),
            cwd=str(Path(__file__).resolve().parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=MAX_PLAGIARISM_RUNTIME_SECONDS,
            )
        except asyncio.TimeoutError as error:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise HTTPException(
                status_code=504,
                detail="The document check exceeded its 90-second time limit. Shorten the document and retry.",
            ) from error
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode != 0:
            raise RuntimeError(f"Plagiarism worker exited with status {process.returncode}.")
        try:
            result = json.loads(stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("Plagiarism worker returned an invalid response.") from error
        if not isinstance(result, dict):
            raise RuntimeError("Plagiarism worker returned an unexpected response.")
        return result


app.add_middleware(
    CORSMiddleware,
    allow_origins=_configured_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Models
class ProjectSubmission(StrictRequest):
    project_name: str = Field(min_length=1, max_length=200)
    project_abstract: str = Field(default="", max_length=10000)

class CreateTeamRequest(StrictRequest):
    team_name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    max_members: int = Field(default=4, ge=2, le=10)

class JoinTeamRequest(StrictRequest):
    team_code: str = Field(min_length=4, max_length=12, pattern=r"^[A-Za-z0-9]+$")

class TeamInviteRequest(StrictRequest):
    invitee_roll_no: str = Field(min_length=1, max_length=64)

class TeamInviteResponse(StrictRequest):
    action: Literal["accept", "decline"]

class MentorStudentUpdate(StrictRequest):
    student_name: str = Field(min_length=1, max_length=150)
    prn: str = Field(default="", max_length=64)
    group_number: str = Field(default="", max_length=100)
    project_name: str = Field(default="", max_length=200)
    year: str = Field(default="", max_length=64)

class MentorStudentCreate(MentorStudentUpdate):
    pass

class MentorReviewCreate(StrictRequest):
    group_number: str = Field(min_length=1, max_length=100)
    review_type: str = Field(min_length=1, max_length=64)
    review_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    review_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    notes: str = Field(default="", max_length=2000)

class MentorReviewStatus(StrictRequest):
    status: Literal["completed", "cancelled"]

class AxiomChatTurn(StrictRequest):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)

class MentorAxiomRequest(StrictRequest):
    project_id: int = Field(gt=0)
    question: str = Field(min_length=1, max_length=4000)
    history: list[AxiomChatTurn] = Field(default_factory=list, max_length=8)

# Endpoints
@app.get("/chat-stream")
async def chat_stream(prompt: Annotated[str, Query(min_length=1, max_length=4000)]):
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
    mentor_user = require_profile_role(request, "mentor")["identifier"]
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(
            func.lower(Mentor.username) == mentor_user.strip().lower()
        ).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        project = mentor_projects(db, mentor.id).filter(Project.id == data.project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found or not available to this mentor.")
        title = (project.project_name or "Untitled project")[:500]
        abstract = (project.project_abstract or "")[:5000]
        group_name = str(project.group_no or "")[:200]
        year = (project.year or "")[:100]
    finally:
        db.close()

    question = data.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Enter a question for Axiom AI.")
    history_lines = []
    for turn in data.history[-8:]:
        role = "Mentor" if turn.role == "user" else "Axiom AI"
        content = " ".join(turn.content.split())[:2000]
        if content:
            history_lines.append(f"{role}: {content}")
    prompt = "\n".join([
        "Help a mentor review the following academic project.",
        f"Project title: {title[:500]}",
        f"Project abstract: {abstract or 'Not provided'}",
        f"Group: {group_name or 'Not provided'}",
        f"Year: {year or 'Not provided'}",
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
        student = db.query(Student).filter(
            func.lower(Student.roll_no) == roll_no.strip().lower()
        ).with_for_update().first()
        if not student:
            raise HTTPException(status_code=404, detail="Student account not found.")
        if db.query(TeamMember).filter(func.lower(TeamMember.roll_no) == roll_no.strip().lower()).first():
            raise HTTPException(status_code=400, detail="You are already in a team. You cannot create another one.")

        code = generate_team_code()
        while db.query(Team).filter(Team.team_code == code).first():
            code = generate_team_code()

        new_team = Team(
            team_name=data.team_name.strip(),
            team_code=code,
            description=data.description,
            max_members=data.max_members,
            year=student.year,
            created_by_student_id=student.id,
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
        logger.error("Team creation failed (%s)", type(e).__name__)
        raise HTTPException(status_code=500, detail="Could not create the team.") from e
    finally:
        db.close()

@app.post("/join-team")
def join_team(data: JoinTeamRequest, request: Request):
    profile = require_profile_role(request, "student")
    roll_no = profile["identifier"]
    db = SessionLocal()
    try:
        student = db.query(Student).filter(
            func.lower(Student.roll_no) == roll_no.strip().lower()
        ).with_for_update().first()
        if not student:
            raise HTTPException(status_code=404, detail="Student account not found.")
        if db.query(TeamMember).filter(func.lower(TeamMember.roll_no) == roll_no.strip().lower()).first():
            raise HTTPException(status_code=400, detail="You are already in a team. You cannot join multiple teams.")

        team = db.query(Team).filter(Team.team_code == data.team_code).with_for_update().first()
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
        logger.error("Team join failed (%s)", type(e).__name__)
        raise HTTPException(status_code=500, detail="Could not join the team.") from e
    finally:
        db.close()

@app.get("/get-student-team")
def get_student_team(request: Request):
    roll_no = require_profile_role(request, "student")["identifier"]
    db = SessionLocal()
    try:
        member = db.query(TeamMember).filter(
            func.lower(TeamMember.roll_no) == roll_no.strip().lower()
        ).first()
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
        logger.error("Student team lookup failed (%s)", type(e).__name__)
        raise HTTPException(status_code=500, detail="Could not load the team.") from e
    finally:
        db.close()

@app.post("/leave-team")
def leave_team(request: Request):
    roll_no = require_profile_role(request, "student")["identifier"]
    db = SessionLocal()
    try:
        student = db.query(Student).filter(
            func.lower(Student.roll_no) == roll_no.strip().lower()
        ).with_for_update().first()
        if not student:
            raise HTTPException(status_code=404, detail="Student account not found.")
        member = db.query(TeamMember).filter(
            func.lower(TeamMember.roll_no) == roll_no.strip().lower()
        ).first()
        if not member:
            raise HTTPException(status_code=400, detail="You are not currently in a team.")
        
        team = db.query(Team).filter(Team.id == member.team_id).with_for_update().first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")
        team_id = team.id
        db.delete(member)
        # Clean up empty teams
        remaining_members = db.query(TeamMember).filter(TeamMember.team_id == team_id).count()
        if remaining_members == 0:
            has_project = db.query(Project.id).filter(Project.team_id == team_id).first()
            team = db.query(Team).filter(Team.id == team_id).first() if not has_project else None
            if team:
                db.delete(team)
        db.commit()
        return {"message": "Successfully left the team"}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("Leaving team failed (%s)", type(e).__name__)
        raise HTTPException(status_code=500, detail="Could not leave the team.") from e
    finally:
        db.close()

@app.post("/submit-project")
def submit_project(data: ProjectSubmission, request: Request):
    roll_no = require_profile_role(request, "student")["identifier"]
    db = SessionLocal()
    try:
        # Find if the user is in a team
        member = db.query(TeamMember).filter(
            func.lower(TeamMember.roll_no) == roll_no.strip().lower()
        ).first()
        if not member:
            raise HTTPException(status_code=400, detail="You must join a team to submit a project")
        team = db.query(Team).filter(Team.id == member.team_id).with_for_update().first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        member_count = db.query(TeamMember).filter(TeamMember.team_id == team.id).count()
        if member_count < 2:
            raise HTTPException(status_code=400, detail="At least two students must be in the team before submitting a project idea.")

        student = db.query(Student).filter(func.lower(Student.roll_no) == roll_no.strip().lower()).first()
        if not student:
            raise HTTPException(status_code=404, detail="Student account not found.")
        project_name = data.project_name.strip()
        project_abstract = data.project_abstract.strip()
        if not project_name:
            raise HTTPException(status_code=422, detail="Project title is required.")

        project = db.query(Project).filter(Project.team_id == team.id).with_for_update().first()
        if project is None:
            project = Project(team_id=team.id)
            db.add(project)
        # Students overwrite only the team project's content. The mentor assignment
        # and roster ownership fields are preserved on resubmission.
        project.year = student.year or team.year or ""
        project.group_no = None
        project.project_name = project_name
        project.project_abstract = project_abstract
        project.team_name = team.team_name
        project.submitted_by_student_id = student.id
        if engine.dialect.name == "postgresql":
            text = f"{project_name}. {project_abstract}".strip()
            project.embedding = CloudflareEmbeddingClient().embed(text)
        member_rolls = [
            row.roll_no for row in db.query(TeamMember).filter(TeamMember.team_id == team.id).all()
            if row.roll_no
        ]
        if member_rolls:
            for roster_entry in db.query(MentorStudent).filter(
                func.lower(MentorStudent.prn).in_([value.strip().casefold() for value in member_rolls])
            ).all():
                # Mirror only the student-owned project title into mentor roster views.
                roster_entry.project_name = project_name
        db.commit()
        db.refresh(project)
        return {
            "message": "Project idea submitted and updated for your team.",
            "project_id": project.id,
            "assigned_mentor": project.assigned_mentor_id is not None,
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("Project submission persistence failed (%s)", type(e).__name__)
        raise HTTPException(status_code=500, detail="Could not save the project.") from e
    finally:
        db.close()

@app.post("/check-plagiarism")
async def check_plagiarism(
    request: Request,
    file: Annotated[UploadFile | None, File()] = None,
    title: Annotated[str, Form(max_length=500)] = "",
    description: Annotated[str, Form(max_length=10000)] = "",
):
    require_profile_role(request, "student")
    try:
        try:
            await asyncio.wait_for(_plagiarism_semaphore.acquire(), timeout=2)
        except asyncio.TimeoutError as error:
            raise HTTPException(
                status_code=429,
                detail="Document checks are busy. Please try again shortly.",
                headers={"Retry-After": "15"},
            ) from error
        try:
            file_bytes = await file.read(MAX_PLAGIARISM_UPLOAD_BYTES + 1) if file else b""
            if len(file_bytes) > MAX_PLAGIARISM_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="The uploaded file must be 20 MB or smaller.")
            filename = (file.filename or "") if file else ""
            result = await run_plagiarism_check_with_deadline(
                title, description, file_bytes, filename
            )
            if "error" in result:
                raise HTTPException(status_code=400, detail=result["error"])
            if request.state.profile["role"] == "student":
                # Students need the score to decide whether to revise; matching
                # project titles and team metadata expose other students' work.
                result = {
                    key: result[key]
                    for key in ("plagiarism_percent", "risk_level", "document_text_truncated", "document_text_used_characters")
                    if key in result
                }
            return result
        finally:
            _plagiarism_semaphore.release()
    except HTTPException:
        raise
    except DocumentValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except DocumentExtractionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except DocumentLimitError as e:
        raise HTTPException(status_code=413, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 - translate document/parser failures to an API response
        logger.error("Unexpected plagiarism processing failure (%s)", type(e).__name__)
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
    mentor_user = require_profile_role(request, "mentor")["identifier"]
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == mentor_user.strip().lower()).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        projects = mentor_projects(db, mentor.id).order_by(Project.id.desc()).all()
        return [project_summary(project, mentor.id) for project in projects]
    finally:
        db.close()


@app.patch("/api/projects/{project_id}/assign")
def assign_project_to_current_mentor(project_id: int, request: Request):
    mentor_user = require_profile_role(request, "mentor")["identifier"]
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == mentor_user.strip().lower()).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project or project.team_id is None:
            raise HTTPException(status_code=404, detail="Team project not found.")
        team_id = project.team_id
        team = db.query(Team).filter(Team.id == team_id).with_for_update().first()
        if not team:
            raise HTTPException(status_code=404, detail="Project team not found.")
        project = db.query(Project).filter(
            Project.id == project_id, Project.team_id == team_id
        ).populate_existing().with_for_update().first()
        if not project:
            raise HTTPException(status_code=404, detail="Team project not found.")
        if project.assigned_mentor_id not in (None, mentor.id):
            raise HTTPException(status_code=409, detail="This team project is already assigned to another mentor.")

        db.query(TeamMember).filter(TeamMember.team_id == team.id).with_for_update().all()
        members: list[TeamMember] = db.query(TeamMember).filter(TeamMember.team_id == team.id).all()
        roll_numbers = [member.roll_no for member in members if member.roll_no]
        if not roll_numbers:
            raise HTTPException(status_code=409, detail="This project has no current team members.")
        mentor_key_value = mentor_key(mentor.username)
        existing_roster = db.query(MentorStudent).filter(
            func.lower(MentorStudent.prn).in_([value.strip().casefold() for value in roll_numbers])
        ).all()
        roster_by_prn = {
            entry.prn.strip().casefold(): entry for entry in existing_roster if entry.prn
        }
        normalized_roll_numbers = [value.strip().casefold() for value in roll_numbers]
        if len(normalized_roll_numbers) != len(set(normalized_roll_numbers)):
            raise HTTPException(status_code=409, detail="This team's membership data contains duplicate student IDs.")
        for roll_number in roll_numbers:
            entry = roster_by_prn.get(roll_number.strip().casefold())
            if entry and entry.mentor_key != mentor_key_value:
                raise HTTPException(
                    status_code=409,
                    detail="A team member is already assigned to another mentor. Contact an administrator to resolve the roster.",
                )

        project.assigned_mentor_id = mentor.id
        project.mentor_assigned_at = project.mentor_assigned_at or datetime.now().isoformat(timespec="seconds")
        for roll_number in roll_numbers:
            student = db.query(Student).filter(
                func.lower(Student.roll_no) == roll_number.casefold()
            ).first()
            entry = roster_by_prn.get(roll_number.strip().casefold())
            if entry is None:
                entry = MentorStudent(
                    mentor_name=mentor.username,
                    mentor_key=mentor_key_value,
                    student_name=roll_number,
                    prn=roll_number,
                    group_name=team.team_name,
                    year=student.year if student else team.year,
                )
                db.add(entry)
            else:
                entry.mentor_name = mentor.username
                entry.mentor_key = mentor_key_value
                entry.student_name = entry.student_name or roll_number
                entry.group_name = entry.group_name or team.team_name
                entry.year = entry.year or (student.year if student else team.year)
            # This is the student-owned project field mirrored into the mentor roster.
            entry.project_name = project.project_name
        db.commit()
        return {
            "message": "You are now assigned to this team's project.",
            "project_id": project.id,
            "team_id": team.id,
            "team_name": team.team_name,
            "assigned_to_me": True,
        }
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as error:
        db.rollback()
        logger.error("Project assignment failed (%s)", type(error).__name__)
        raise HTTPException(status_code=500, detail="Could not assign the project.") from error
    finally:
        db.close()


@app.get("/api/students")
def get_students(request: Request) -> list[dict[str, str | int | None]]:
    mentor_user = require_profile_role(request, "mentor")["identifier"]
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == mentor_user.strip().lower()).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        roster: list[MentorStudent] = db.query(MentorStudent).filter(
            MentorStudent.mentor_key == mentor_key(mentor.username)
        ).order_by(MentorStudent.student_name).all()
        roster = roster_for_project_owners(db, roster)
        result: list[dict[str, str | int | None]] = []
        for entry in roster:
            team_name = "No Team"
            project_name = entry.project_name or "No Project"
            if entry.prn:
                member = db.query(TeamMember).filter(
                    func.lower(TeamMember.roll_no) == entry.prn.strip().lower()
                ).first()
            else:
                member = None
            if member:
                team = db.query(Team).filter(Team.id == member.team_id).first()
                if team:
                    team_name = team.team_name
                    project = db.query(Project).filter(Project.team_id == team.id).first()
                    if project and project.assigned_mentor_id in (None, mentor.id):
                        project_name = project.project_name or project_name
                    elif project:
                        team_name = "No Team"
                        project_name = "No Project"
            
            result.append({
                "roll_no": entry.prn or "",
                "year": entry.year,
                "team_name": team_name,
                "project_name": project_name,
                "submissions": "1 / 1" if project_name != "No Project" else "0 / 1"
            })
        return result
    finally:
        db.close()


@app.post("/mentor/students/import")
async def import_mentor_students(file: Annotated[UploadFile, File()], request: Request):
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
            students = [row for row in parse_mentor_roster(content, mentor.username)
                        if row["mentor_key"] == mentor_key(mentor.username)]
        except (ValueError, InvalidFileException, BadZipFile) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not students:
            raise HTTPException(status_code=400, detail="The sheet has no students assigned to this mentor. Your roster was not changed.")

        # An upload represents the mentor's complete current roster. Reject duplicate
        # PRNs or students assigned elsewhere before replacing any saved rows.
        incoming_prns = [row["prn"].strip().casefold() for row in students if row["prn"].strip()]
        if len(incoming_prns) != len(set(incoming_prns)):
            raise HTTPException(status_code=400, detail="The roster contains duplicate student PRNs.")
        current_mentor_key = mentor_key(mentor.username)
        for prn in incoming_prns:
            other_owner = db.query(MentorStudent).filter(
                func.lower(MentorStudent.prn) == prn,
                MentorStudent.mentor_key != current_mentor_key,
            ).first()
            if other_owner:
                raise HTTPException(
                    status_code=409,
                    detail="A student in this sheet is assigned to another mentor. Contact an administrator to change that assignment.",
                )
            # A roster upload cannot create an alternate route to a project
            # assigned to another mentor, even if that mentor removed the PRN
            # from their spreadsheet roster.
            _project_available_to_mentor(db, prn, mentor.id)

        added = 0
        updated = 0
        retained_ids: set[int] = set()
        for row in students:
            # An uploaded sheet can describe students and groups, but it cannot
            # assign rows to a different mentor account.
            row["mentor_name"] = mentor.username
            row["mentor_key"] = current_mentor_key
            if row["prn"]:
                existing = db.query(MentorStudent).filter(
                    func.lower(MentorStudent.prn) == row["prn"].strip().casefold()
                ).first()
            else:
                existing = db.query(MentorStudent).filter(
                    MentorStudent.mentor_key == current_mentor_key,
                    func.lower(MentorStudent.student_name) == row["student_name"].lower(),
                ).first()
            if existing:
                retained_ids.add(existing.id)
                updated += 1
            else:
                existing = MentorStudent()
                db.add(existing)
                added += 1
            existing.mentor_name = mentor.username
            existing.mentor_key = current_mentor_key
            existing.student_name = row["student_name"]
            existing.prn = row["prn"] or None
            existing.group_name = row["group_name"] or None
            existing.year = row["year"] or None
            team_project = _team_project_for_student(db, row["prn"]) if row["prn"] else None
            # Project titles submitted by a student are canonical and cannot be
            # replaced by a stale roster spreadsheet.
            existing.project_name = (
                team_project.project_name if team_project else row["project_name"] or None
            )
        stale_rows = db.query(MentorStudent).filter(
            MentorStudent.mentor_key == current_mentor_key
        ).all()
        removed = 0
        for stale in stale_rows:
            if stale.id not in retained_ids and (not stale.prn or stale.prn.strip().casefold() not in incoming_prns):
                db.delete(stale)
                removed += 1
        db.commit()
        return {"added": added, "updated": updated, "removed": removed, "total": len(students)}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise
    finally:
        db.close()


@app.get("/mentor/students")
def get_mentor_students(request: Request) -> list[dict[str, str | int]]:
    mentor_user = require_profile_role(request, "mentor")["identifier"]
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == mentor_user.strip().lower()).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        roster: list[MentorStudent] = db.query(MentorStudent).filter(
            MentorStudent.mentor_key == mentor_key(mentor.username)
        ).order_by(MentorStudent.student_name).all()
        roster = roster_for_project_owners(db, roster)
        result: list[dict[str, str | int]] = []
        for entry in roster:
            team_name = entry.group_name or "No Group"
            project_name = entry.project_name or "No Project"
            if entry.prn:
                member = db.query(TeamMember).filter(
                    func.lower(TeamMember.roll_no) == entry.prn.strip().lower()
                ).first()
                if member:
                    team = db.query(Team).filter(Team.id == member.team_id).first()
                    if team:
                        team_name = team.team_name or "No Group"
                        project = db.query(Project).filter(Project.team_id == team.id).first()
                        if project and project.assigned_mentor_id in (None, mentor.id):
                            project_name = project.project_name or "No Project"
                        elif project:
                            team_name = entry.group_name or "No Group"
                            project_name = "No Project"
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
        inviter_student = db.query(Student).filter(
            func.lower(Student.roll_no) == inviter_roll.strip().lower()
        ).with_for_update().first()
        if not inviter_student:
            raise HTTPException(status_code=404, detail="Student account not found.")
        invitee = db.query(Student).filter(
            func.lower(Student.roll_no) == invitee_input.lower()
        ).first()
        if not invitee:
            raise HTTPException(status_code=404, detail="No registered student has that PRN or roll number.")
        inviter_member = db.query(TeamMember).filter(
            func.lower(TeamMember.roll_no) == inviter_roll.strip().lower()
        ).first()
        if not inviter_member:
            raise HTTPException(status_code=400, detail="You must be in a team before inviting members.")
        team = db.query(Team).filter(Team.id == inviter_member.team_id).with_for_update().first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")
        if invitee.roll_no.lower() == inviter_roll.lower():
            raise HTTPException(status_code=400, detail="You cannot invite yourself.")
        if db.query(TeamMember).filter(func.lower(TeamMember.roll_no) == invitee.roll_no.lower()).first():
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
def get_team_invitations(request: Request):
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
                    "inviter_roll_no": invitation.inviter_roll_no,
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
        student = db.query(Student).filter(
            func.lower(Student.roll_no) == roll_no.strip().lower()
        ).with_for_update().first()
        if not student:
            raise HTTPException(status_code=404, detail="Student account not found.")
        invitation = db.query(TeamInvitation).filter(
            TeamInvitation.id == invitation_id,
            func.lower(TeamInvitation.invitee_roll_no) == roll_no.strip().lower(),
            TeamInvitation.status == "pending",
        ).with_for_update().first()
        if not invitation:
            raise HTTPException(status_code=404, detail="Invitation is no longer available.")
        if action == "decline":
            invitation.status = "declined"
            invitation.responded_at = datetime.now().isoformat(timespec="seconds")
            db.commit()
            return {"message": "Invitation declined.", "status": "declined"}
        if db.query(TeamMember).filter(
            func.lower(TeamMember.roll_no) == invitation.invitee_roll_no.strip().lower()
        ).first():
            raise HTTPException(status_code=409, detail="You are already in a team.")
        team = db.query(Team).filter(Team.id == invitation.team_id).with_for_update().first()
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
def get_mentor_dashboard(request: Request):
    mentor_user = require_profile_role(request, "mentor")["identifier"]
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(func.lower(Mentor.username) == mentor_user.strip().lower()).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor account not found.")
        key = mentor_key(mentor.username)
        students = db.query(MentorStudent).filter(MentorStudent.mentor_key == key).all()
        students = roster_for_project_owners(db, students)
        reviews = db.query(MentorReview).filter(MentorReview.mentor_key == key).order_by(
            MentorReview.created_at.desc(), MentorReview.id.desc()
        ).all()
        projects = {
            project.id
            for student in students
            if student.prn
            for project in [
                db.query(Project.id)
                .join(TeamMember, TeamMember.team_id == Project.team_id)
                .join(Team, Team.id == Project.team_id)
                .filter(
                    func.lower(TeamMember.roll_no) == student.prn.strip().lower(),
                    or_(Project.assigned_mentor_id.is_(None), Project.assigned_mentor_id == mentor.id),
                )
                .first()
            ]
            if project
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
            raise HTTPException(status_code=409, detail="This PRN is already assigned to a mentor. Contact an administrator to change the assignment.")
        team_project = _project_available_to_mentor(db, prn, mentor.id) if prn else None
        entry = MentorStudent(
            mentor_name=mentor.username,
            mentor_key=mentor_key(mentor.username),
            student_name=name,
            prn=prn or None,
            group_name=data.group_number.strip() or None,
            project_name=team_project.project_name if team_project else data.project_name.strip() or None,
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
            func.lower(MentorStudent.prn) == prn.lower(),
            MentorStudent.id != roster_id,
        ).first():
            raise HTTPException(status_code=409, detail="Another student already has this PRN.")
        team_project = _project_available_to_mentor(db, prn, mentor.id) if prn else None
        entry.student_name = name
        entry.prn = prn or None
        entry.group_name = data.group_number.strip() or None
        entry.project_name = team_project.project_name if team_project else data.project_name.strip() or None
        entry.year = data.year.strip() or None
        db.commit()
        return {"message": "Student updated."}
    finally:
        db.close()


@app.delete("/mentor/students/{roster_id}")
def delete_mentor_student(roster_id: int, request: Request):
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


def require_enrollment_admin(request: Request):
    allowed = {value.strip() for value in os.getenv('ENROLLMENT_ADMIN_CLERK_USER_IDS', '').split(',') if value.strip()}
    if request.state.clerk_user_id not in allowed:
        raise HTTPException(403, 'Administrator access is required.')


class AdminEnrollmentRequest(StrictRequest):
    roll_no: str = Field(min_length=1, max_length=64)
    year: str = Field(min_length=1, max_length=64)
    expires_hours: int = Field(default=168, ge=1, le=8760)


@app.get('/api/admin/enrollments')
def list_enrollments(request: Request):
    require_enrollment_admin(request)
    with SessionLocal() as db:
        return [{'id': row.id, 'roll_no': row.roll_no, 'year': row.year,
                 'expires_at': row.expires_at, 'used_at': row.used_at, 'revoked_at': row.revoked_at}
                for row in db.query(EnrollmentCode).order_by(EnrollmentCode.id.desc()).limit(200)]


@app.post('/api/admin/enrollments')
def issue_enrollment(data: AdminEnrollmentRequest, request: Request):
    require_enrollment_admin(request)
    with SessionLocal() as db:
        profiles = db.query(Student).filter(func.lower(func.trim(Student.roll_no)) == data.roll_no.lower()).all()
        if len(profiles) > 1 or any(row.clerk_user_id for row in profiles):
            raise HTTPException(409, 'This roll number already has a linked or ambiguous profile.')
        code = secrets.token_urlsafe(24)
        now = int(time.time())
        grant = EnrollmentCode(code_hash=code_hash(code), roll_no=data.roll_no, year=data.year,
                               created_at=now, expires_at=now + data.expires_hours * 3600)
        db.add(grant)
        db.commit()
        return {'id': grant.id, 'code': code, 'expires_at': grant.expires_at}


@app.post('/api/admin/enrollments/{enrollment_id}/revoke')
def revoke_enrollment(enrollment_id: int, request: Request):
    require_enrollment_admin(request)
    with SessionLocal() as db:
        grant = db.query(EnrollmentCode).filter(EnrollmentCode.id == enrollment_id).with_for_update().first()
        if not grant:
            raise HTTPException(404, 'Enrollment not found.')
        grant.revoked_at = int(time.time())
        db.commit()
        return {'message': 'Enrollment revoked.'}
