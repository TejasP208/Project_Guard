import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

load_dotenv()

# Keep SQLite as the local development default. Set DATABASE_URL to a
# PostgreSQL connection string in deployment (or in the local .env file).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./DB/training_data.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine_options = {}
if DATABASE_URL.startswith("sqlite:"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)

SessionLocal = sessionmaker(bind=engine)


def migrate_database():
    """Apply safe additive project, mentor-roster, and vector migrations."""
    project_columns = {column["name"] for column in inspect(engine).get_columns("projects")}
    if "team_name" not in project_columns:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE projects ADD COLUMN team_name VARCHAR")
    if inspect(engine).has_table("mentor_students"):
        roster_columns = {column["name"] for column in inspect(engine).get_columns("mentor_students")}
        if "project_name" not in roster_columns:
            with engine.begin() as connection:
                connection.exec_driver_sql("ALTER TABLE mentor_students ADD COLUMN project_name VARCHAR")
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            connection.exec_driver_sql(
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS embedding vector(1024)"
            )
