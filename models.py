from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import declarative_base
from pgvector.sqlalchemy import VECTOR

Base = declarative_base()

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
    # Qwen3 embeddings from Cloudflare Workers AI use 1024 dimensions.
    # Kept nullable so existing SQLite/PostgreSQL project rows remain valid.
    embedding = Column(VECTOR(1024), nullable=True)

class Mentor(Base):
    __tablename__ = "mentors"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)


# 🔥 Team table
class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    # Team names are not unique in existing project data; team_code is the identifier.
    team_name = Column(String)
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
