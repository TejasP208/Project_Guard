"""Preview or remove password columns left by the retired local login system.

Run without flags to see counts. Use --apply only after confirming the target
database and backup policy; this discards legacy password hashes permanently.
"""

import argparse

from sqlalchemy import inspect, text

from database import engine

TABLES = ("students", "mentors", "teams")


def password_columns(connection):
    inspector = inspect(connection)
    return [table for table in TABLES if "password" in {
        column["name"] for column in inspector.get_columns(table)
    }]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Permanently remove legacy password columns")
    args = parser.parse_args()
    with engine.begin() as connection:
        if engine.dialect.name != "postgresql":
            parser.error("This migration requires PostgreSQL.")
        tables = password_columns(connection)
        counts = {table: connection.execute(text(f"SELECT count(*) FROM {table} WHERE password IS NOT NULL")).scalar_one()
                  for table in tables}
        print({"password_columns": tables, "non_null_values": counts, "applied": args.apply})
        if args.apply:
            for table in tables:
                connection.exec_driver_sql(f"UPDATE {table} SET password = NULL WHERE password IS NOT NULL")
                connection.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN password")


if __name__ == "__main__":
    main()
