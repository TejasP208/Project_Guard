"""Copy the local SQLite application data into an empty PostgreSQL database.

Set DATABASE_URL to the PostgreSQL connection URL before running this script.
The source SQLite database is read-only and is never modified.
"""

import os
import sqlite3

from sqlalchemy import func, select, text

from database import engine
from models import Base


SOURCE_DB = os.path.join(os.path.dirname(__file__), "DB", "training_data.db")
TABLE_NAMES = ("students", "mentors", "teams", "team_members", "projects")


def migrate():
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Set DATABASE_URL to a PostgreSQL URL before running this script.")
    if not os.path.isfile(SOURCE_DB):
        raise FileNotFoundError(f"SQLite source database not found: {SOURCE_DB}")

    Base.metadata.create_all(bind=engine)
    tables = {name: Base.metadata.tables[name] for name in TABLE_NAMES}

    with sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        source_table_names = {
            row[0]
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = set(TABLE_NAMES) - source_table_names
        if missing:
            raise RuntimeError(f"SQLite source is missing tables: {', '.join(sorted(missing))}")

        source_rows = {
            name: source.execute(f'SELECT * FROM "{name}"').fetchall()
            for name in TABLE_NAMES
        }

    with engine.begin() as target:
        nonempty = []
        for name, table in tables.items():
            count = target.scalar(select(func.count()).select_from(table))
            if count:
                nonempty.append(name)
        if nonempty:
            raise RuntimeError(
                "Refusing to copy into non-empty PostgreSQL tables: "
                + ", ".join(nonempty)
                + ". Use a fresh/empty database to avoid duplicate or overwritten records."
            )

        for name in TABLE_NAMES:
            table = tables[name]
            destination_columns = set(table.columns.keys())
            rows = [
                {key: value for key, value in dict(row).items() if key in destination_columns}
                for row in source_rows[name]
            ]
            if name == "projects":
                for row in rows:
                    row.setdefault("team_name", None)
            if rows:
                target.execute(table.insert(), rows)

            # Explicit IDs are preserved during the copy; advance PostgreSQL's
            # generated-ID sequence so new records continue after the imported rows.
            if rows and "id" in destination_columns:
                target.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                        f"(SELECT MAX(id) FROM \"{name}\"), true)"
                    ),
                    {"table_name": name},
                )
            print(f"Imported {len(rows)} rows from {name}.")


if __name__ == "__main__":
    migrate()
