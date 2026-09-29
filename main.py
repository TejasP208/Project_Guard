from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import StreamingResponse
from axiom_ai import Chatbot_stream
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from database import engine, SessionLocal, migrate_database
from models import Base, Project, Team, TeamMember, Student, Mentor
from passlib.hash import pbkdf2_sha256
from fastapi import HTTPException
from pydantic import BaseModel
import os
from utils import generate_team_code
from nlp.checker import run_plagiarism_check
from embeddings import CloudflareEmbeddingClient

# Initialize DB
Base.metadata.create_all(bind=engine)
migrate_database()

app = FastAPI()

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
    roll_no: str = None

class JoinTeamRequest(BaseModel):
    team_code: str
    roll_no: str

class LeaveTeamRequest(BaseModel):
    roll_no: str

class MentorSignupRequest(BaseModel):
    username: str
    password: str

class MentorLoginRequest(BaseModel):
    username: str
    password: str

# Endpoints
@app.get("/chat-stream")
def chat_stream(prompt: str):
    return StreamingResponse(Chatbot_stream(prompt), media_type="text/plain")

@app.post("/signup")
def signup(data: SignupRequest):
    db = SessionLocal()
    try:
        if db.query(Student).filter(Student.roll_no == data.roll_no).first():
            raise HTTPException(status_code=400, detail="Roll number already registered")
        
        hashed_password = pbkdf2_sha256.hash(data.password)
        new_student = Student(
            roll_no=data.roll_no,
            password=hashed_password,
            year=data.year
        )
        db.add(new_student)
        db.commit()
        return {"message": "Signup successful"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/login")
def login(data: LoginRequest):
    db = SessionLocal()
    try:
        student = db.query(Student).filter(Student.roll_no == data.roll_no).first()
        if not student or not pbkdf2_sha256.verify(data.password, student.password):
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
        if data.roll_no:
            if db.query(TeamMember).filter(TeamMember.roll_no == data.roll_no).first():
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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/join-team")
def join_team(data: JoinTeamRequest):
    db = SessionLocal()
    try:
        if data.roll_no:
            if db.query(TeamMember).filter(TeamMember.roll_no == data.roll_no).first():
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
    except Exception as e:
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
    except Exception as e:
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
    except Exception as e:
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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/check-plagiarism")
async def check_plagiarism(
    title: str = Form(""),
    description: str = Form(""),
    file: UploadFile = File(...)
):
    try:
        file_bytes = await file.read()
        result = await run_in_threadpool(
            run_plagiarism_check, title, description, file_bytes, file.filename
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Mentor Endpoints ──────────────────────────────────────────────

@app.post("/mentor/signup")
def mentor_signup(data: MentorSignupRequest):
    db = SessionLocal()
    try:
        if db.query(Mentor).filter(Mentor.username == data.username).first():
            raise HTTPException(status_code=400, detail="Username already registered")

        hashed_password = pbkdf2_sha256.hash(data.password)
        new_mentor = Mentor(
            username=data.username,
            password=hashed_password
        )
        db.add(new_mentor)
        db.commit()
        return {"message": "Mentor account created successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/mentor/login")
def mentor_login(data: MentorLoginRequest):
    db = SessionLocal()
    try:
        mentor = db.query(Mentor).filter(Mentor.username == data.username).first()
        if not mentor or not pbkdf2_sha256.verify(data.password, mentor.password):
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
def get_students():
    db = SessionLocal()
    try:
        students = db.query(Student).all()
        result = []
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
