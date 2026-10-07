"""Audit identity relationships without deleting or choosing between records."""

import argparse
import json
from collections import defaultdict

from mentor_roster import mentor_key
from models import Mentor, MentorStudent, Student, Team, TeamInvitation, TeamMember


def normalized(value):
    return (value or "").strip().lower()


def duplicates(rows, field, normalize=normalized):
    groups = defaultdict(list)
    for row in rows:
        value = normalize(getattr(row, field))
        if value:
            groups[value].append(row.id)
    return [ids for ids in groups.values() if len(ids) > 1]


def audit_identities(db):
    # Explicit columns allow this audit to run before additive migrations.
    students = db.query(Student.id, Student.roll_no, Student.clerk_user_id).all()
    mentors = db.query(Mentor.id, Mentor.username, Mentor.clerk_user_id).all()
    members = db.query(TeamMember.id, TeamMember.roll_no, TeamMember.team_id).all()
    roster = db.query(MentorStudent.id, MentorStudent.prn, MentorStudent.mentor_key).all()
    invitations = db.query(TeamInvitation.id, TeamInvitation.team_id).all()
    teams = {row.id for row in db.query(Team.id).all()}
    subjects = defaultdict(list)
    for kind, rows in (("student", students), ("mentor", mentors)):
        for row in rows:
            if row.clerk_user_id:
                subjects[row.clerk_user_id].append({"role": kind, "id": row.id})
    conflicts = {
        "duplicate_student_identifiers": duplicates(students, "roll_no"),
        "duplicate_mentor_usernames": duplicates(mentors, "username"),
        "duplicate_mentor_ownership_keys": duplicates(mentors, "username", mentor_key),
        "duplicate_membership_identifiers": duplicates(members, "roll_no"),
        "duplicate_roster_prns": duplicates(roster, "prn"),
        "multiple_profiles_for_clerk_subject": [rows for rows in subjects.values() if len(rows) > 1],
        "invalid_student_identifiers": [row.id for row in students if not normalized(row.roll_no)],
        "invalid_mentor_identifiers": [row.id for row in mentors if not mentor_key(row.username)],
        "invalid_memberships": [row.id for row in members if not normalized(row.roll_no) or row.team_id not in teams],
        "orphaned_team_invitations": [row.id for row in invitations if row.team_id not in teams],
    }
    return {"counts": {"students": len(students), "mentors": len(mentors), "memberships": len(members),
                       "roster_rows": len(roster), "invitations": len(invitations)},
            "conflicts": conflicts, "safe_to_constrain": not any(conflicts.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply reviewed normalization and constraints only if the audit is clean")
    args = parser.parse_args()
    from database import SessionLocal
    with SessionLocal() as db:
        if args.apply:
            # Prevent concurrent writes between the audit and index creation.
            from sqlalchemy import text
            db.execute(text("LOCK TABLE students, mentors, teams, team_members, mentor_students, team_invitations IN SHARE ROW EXCLUSIVE MODE"))
        result = audit_identities(db)
        if args.apply:
            if not result["safe_to_constrain"]:
                print(json.dumps(result, indent=2))
                parser.error("Resolve conflicting row IDs with an administrator before applying constraints.")
            apply_identity_constraints(db.connection())
            db.commit()
            result["constraints_applied"] = True
        print(json.dumps(result, indent=2))


def apply_identity_constraints(connection):
    """Called only after a clean audit under a write-blocking table lock."""
    for table, field in (("students", "roll_no"), ("mentors", "username"),
                         ("team_members", "roll_no"), ("mentor_students", "prn")):
        predicate = " WHERE prn IS NOT NULL AND btrim(prn) <> ''" if field == "prn" else ""
        connection.exec_driver_sql(
            f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table}_{field}_normalized "
            f"ON {table} (lower(btrim({field}))){predicate}"
        )
    for table, field in (("students", "roll_no"), ("mentors", "username"), ("team_members", "roll_no")):
        name = f"ck_{table}_{field}_nonblank"
        connection.exec_driver_sql(f"""DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}' AND conrelid = '{table}'::regclass) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({field} IS NOT NULL AND btrim({field}) <> '');
            END IF;
        END $$""")
    for table in ("team_members", "team_invitations"):
        name = f"fk_{table}_team"
        connection.exec_driver_sql(f"""DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}' AND conrelid = '{table}'::regclass) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE;
            END IF;
        END $$""")
    connection.exec_driver_sql("ALTER TABLE team_members ALTER COLUMN team_id SET NOT NULL")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Database errors can include credentials or personal row values.
        print(f"Identity audit/migration failed: {type(error).__name__}")
        raise SystemExit(1)
