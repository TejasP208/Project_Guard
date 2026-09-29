from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

# ✅ connect to your existing DB
DATABASE_URL = "sqlite:///./DB/training_data.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine)


def migrate_database():
    """Apply safe, additive schema updates to an existing SQLite database."""
    project_columns = {column["name"] for column in inspect(engine).get_columns("projects")}
    if "team_name" not in project_columns:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE projects ADD COLUMN team_name VARCHAR")
    if inspect(engine).has_table("mentor_students"):
        roster_columns = {column["name"] for column in inspect(engine).get_columns("mentor_students")}
        if "project_name" not in roster_columns:
            with engine.begin() as connection:
                connection.exec_driver_sql("ALTER TABLE mentor_students ADD COLUMN project_name VARCHAR")
