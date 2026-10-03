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


def enable_pgvector():
    """Enable pgvector before SQLAlchemy creates the VECTOR-backed schema."""
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
