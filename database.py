import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

load_dotenv()

# The application database is PostgreSQL only. SQLite is read only by the
# one-time import script and is never used as the live application database.
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set to a PostgreSQL connection URL.")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

if not DATABASE_URL.startswith("postgresql+psycopg://"):
    raise RuntimeError("DATABASE_URL must use PostgreSQL (postgresql:// or postgres://).")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine)


def migrate_database():
    """Apply additive schema changes serially across concurrent API workers."""
    with engine.begin() as connection:
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(20261017, 2)")
        _apply_migrations(connection)


def initialize_database(metadata):
    """Create tables and migrate them under one startup-wide schema lock."""
    with engine.begin() as connection:
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(20261017, 2)")
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        metadata.create_all(bind=connection)
        _apply_migrations(connection)


def _apply_migrations(connection):
    inspector = inspect(connection)
    if inspector.has_table("enrollment_codes"):
        columns = {column["name"] for column in inspector.get_columns("enrollment_codes")}
        if "role" not in columns:
            connection.exec_driver_sql("ALTER TABLE enrollment_codes ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'student'")
        if "issued_by_clerk_user_id" not in columns:
            connection.exec_driver_sql("ALTER TABLE enrollment_codes ADD COLUMN issued_by_clerk_user_id VARCHAR")
        if "verification_method" not in columns:
            connection.exec_driver_sql("ALTER TABLE enrollment_codes ADD COLUMN verification_method VARCHAR(32)")
    for table_name in ("students", "mentors"):
        if not inspector.has_table(table_name):
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "clerk_user_id" not in columns:
            connection.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN clerk_user_id VARCHAR")
        connection.exec_driver_sql(
            f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table_name}_clerk_user_id ON {table_name} (clerk_user_id)"
        )
    if inspector.has_table("students"):
        columns = {column["name"] for column in inspector.get_columns("students")}
        if "department" not in columns:
            connection.exec_driver_sql("ALTER TABLE students ADD COLUMN department VARCHAR")
            connection.exec_driver_sql("UPDATE students SET year = '3'")
        connection.exec_driver_sql("UPDATE students SET department = 'aiml' WHERE department IS NULL")
    if inspector.has_table("mentor_students"):
        roster_columns = {column["name"] for column in inspector.get_columns("mentor_students")}
        if "project_name" not in roster_columns:
            connection.exec_driver_sql("ALTER TABLE mentor_students ADD COLUMN project_name VARCHAR")
    if inspector.has_table("mentor_reviews"):
        review_columns = {column["name"] for column in inspector.get_columns("mentor_reviews")}
        if "team_id" not in review_columns:
            connection.exec_driver_sql("ALTER TABLE mentor_reviews ADD COLUMN team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL")
    if inspector.has_table("teams"):
        team_columns = {column["name"] for column in inspector.get_columns("teams")}
        if "department" not in team_columns:
            connection.exec_driver_sql("ALTER TABLE teams ADD COLUMN department VARCHAR")
            connection.exec_driver_sql("UPDATE teams SET year = '3'")
        if "project_abstract" not in team_columns:
            connection.exec_driver_sql("ALTER TABLE teams ADD COLUMN project_abstract TEXT")
        for review_number in (1, 2, 3):
            column = f"review{review_number}_status"
            if column not in team_columns:
                connection.exec_driver_sql(f"ALTER TABLE teams ADD COLUMN {column} VARCHAR(16) NOT NULL DEFAULT 'not_submitted'")
        connection.exec_driver_sql("UPDATE teams SET department = 'aiml' WHERE department IS NULL")
        if "sheet_group_no" not in team_columns:
            connection.exec_driver_sql("ALTER TABLE teams ADD COLUMN sheet_group_no VARCHAR")
        if "github_url" not in team_columns:
            connection.exec_driver_sql("ALTER TABLE teams ADD COLUMN github_url VARCHAR(300)")
        connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_teams_sheet_group_no ON teams (sheet_group_no)")
        if "created_by_student_id" not in team_columns:
            connection.exec_driver_sql(
                "ALTER TABLE teams ADD COLUMN created_by_student_id INTEGER REFERENCES students(id) ON DELETE SET NULL"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_teams_created_by_student_id ON teams (created_by_student_id)"
            )
    if inspector.has_table("project_documents"):
        document_columns = {column["name"] for column in inspector.get_columns("project_documents")}
        if "active" not in document_columns:
            connection.exec_driver_sql(
                "ALTER TABLE project_documents ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE"
            )
        if "index_status" not in document_columns:
            connection.exec_driver_sql(
                "ALTER TABLE project_documents ADD COLUMN index_status VARCHAR(16) NOT NULL DEFAULT 'pending'"
            )
        if "index_error" not in document_columns:
            connection.exec_driver_sql("ALTER TABLE project_documents ADD COLUMN index_error VARCHAR(300)")
    if not inspector.has_table("projects"):
        return
    project_columns = {column["name"] for column in inspector.get_columns("projects")}
    if "team_name" not in project_columns:
        connection.exec_driver_sql("ALTER TABLE projects ADD COLUMN team_name VARCHAR")
    if "embedding" not in project_columns:
        connection.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN embedding vector(1024)"
        )
    if "team_id" not in project_columns:
        connection.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN team_id INTEGER "
            "REFERENCES teams(id) ON DELETE SET NULL"
        )
    if "submitted_by_student_id" not in project_columns:
        connection.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN submitted_by_student_id INTEGER "
            "REFERENCES students(id) ON DELETE SET NULL"
        )
    if "assigned_mentor_id" not in project_columns:
        connection.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN assigned_mentor_id INTEGER "
            "REFERENCES mentors(id) ON DELETE SET NULL"
        )
    if "mentor_assigned_at" not in project_columns:
        connection.exec_driver_sql("ALTER TABLE projects ADD COLUMN mentor_assigned_at VARCHAR")
    if "submission_status" not in project_columns:
        connection.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN submission_status VARCHAR(16) NOT NULL DEFAULT 'pending'"
        )
    if "rejected_by_mentor_id" not in project_columns:
        connection.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN rejected_by_mentor_id INTEGER "
            "REFERENCES mentors(id) ON DELETE SET NULL"
        )
    if "rejected_at" not in project_columns:
        connection.exec_driver_sql("ALTER TABLE projects ADD COLUMN rejected_at VARCHAR")
    connection.exec_driver_sql(
        "UPDATE projects SET submission_status = 'accepted' "
        "WHERE assigned_mentor_id IS NOT NULL AND submission_status = 'pending'"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_team_id "
        "ON projects (team_id) WHERE team_id IS NOT NULL"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_projects_assigned_mentor_id "
        "ON projects (assigned_mentor_id)"
    )


def enable_pgvector():
    """Enable pgvector before SQLAlchemy creates the VECTOR-backed schema."""
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
