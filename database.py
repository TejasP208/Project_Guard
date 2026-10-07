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
    """Apply safe additive application-profile and vector migrations."""
    if inspect(engine).has_table("enrollment_codes"):
        columns = {column["name"] for column in inspect(engine).get_columns("enrollment_codes")}
        if "role" not in columns:
            with engine.begin() as connection:
                connection.exec_driver_sql("ALTER TABLE enrollment_codes ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'student'")
    inspector = inspect(engine)
    for table_name in ("students", "mentors"):
        if not inspector.has_table(table_name):
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "clerk_user_id" not in columns:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    f"ALTER TABLE {table_name} ADD COLUMN clerk_user_id VARCHAR"
                )
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table_name}_clerk_user_id "
                f"ON {table_name} (clerk_user_id)"
            )

    if inspect(engine).has_table("mentor_students"):
        roster_columns = {column["name"] for column in inspect(engine).get_columns("mentor_students")}
        if "project_name" not in roster_columns:
            with engine.begin() as connection:
                connection.exec_driver_sql("ALTER TABLE mentor_students ADD COLUMN project_name VARCHAR")
    if inspect(engine).has_table("teams"):
        team_columns = {column["name"] for column in inspect(engine).get_columns("teams")}
        if "created_by_student_id" not in team_columns:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "ALTER TABLE teams ADD COLUMN created_by_student_id INTEGER "
                    "REFERENCES students(id) ON DELETE SET NULL"
                )
                connection.exec_driver_sql(
                    "CREATE INDEX IF NOT EXISTS ix_teams_created_by_student_id "
                    "ON teams (created_by_student_id)"
                )
    if not inspect(engine).has_table("projects"):
        return
    project_columns = {column["name"] for column in inspect(engine).get_columns("projects")}
    with engine.begin() as connection:
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
