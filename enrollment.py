"""Student and mentor enrollment grants issued by authorized administrators."""
import argparse
import hashlib
import secrets
import time

from fastapi import HTTPException
from sqlalchemy import func, inspect, text
from models import EnrollmentCode, Mentor, Student


def code_hash(code):
    return hashlib.sha256(code.strip().encode()).hexdigest()


def redeem_student(db, subject, roll_no, year, code):
    # All redeemers of an identity serialize, including different codes for it.
    # Profile creation is exclusively through this path for new students.
    if db.bind.dialect.name == "postgresql":
        for key in sorted(("enrollment-subject:" + subject, "enrollment-roll:" + roll_no.strip().lower())):
            db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
    if db.query(Student).filter(Student.clerk_user_id == subject).first() or db.query(Mentor).filter(Mentor.clerk_user_id == subject).first():
        raise HTTPException(409, "This Clerk account already has a profile.")
    grant = db.query(EnrollmentCode).filter(EnrollmentCode.code_hash == code_hash(code)).with_for_update().first()
    now = int(time.time())
    if (not grant or grant.role != "student" or grant.used_at is not None or grant.revoked_at is not None
            or grant.expires_at <= now or grant.roll_no.strip().lower() != roll_no.strip().lower()
            or grant.year != year.strip()):
        raise HTTPException(403, "Enrollment code is invalid, expired, used, revoked, or does not match roll number and year.")
    profiles = db.query(Student).filter(func.lower(func.trim(Student.roll_no)) == grant.roll_no.strip().lower()).with_for_update().all()
    if len(profiles) > 1 or (profiles and profiles[0].clerk_user_id):
        raise HTTPException(409, "This roll number already has a linked or ambiguous profile.")
    profile = profiles[0] if profiles else Student(roll_no=grant.roll_no)
    profile.clerk_user_id = subject
    profile.year = grant.year
    db.add(profile)
    grant.used_at = now
    grant.used_by_clerk_user_id = subject
    db.flush()
    return profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    issue = commands.add_parser("issue")
    issue.add_argument("--role", choices=("student", "mentor"), default="student")
    issue.add_argument("--roll-no", required=True, help="Student roll number or mentor name")
    issue.add_argument("--year", default="", help="Required for student enrollment")
    issue.add_argument("--expires-hours", type=int, default=168)
    revoke = commands.add_parser("revoke")
    revoke.add_argument("--id", type=int, required=True)
    args = parser.parse_args()
    from database import SessionLocal, engine
    # Also usable before starting FastAPI; create only this additive table.
    EnrollmentCode.__table__.create(engine, checkfirst=True)
    if "role" not in {column["name"] for column in inspect(engine).get_columns("enrollment_codes")}:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE enrollment_codes ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'student'")
    with SessionLocal() as db:
        if args.command == "issue":
            roll, year = args.roll_no.strip(), args.year.strip()
            if not roll or (args.role == "student" and not year) or len(roll) > 64 or len(year) > 64 or not 1 <= args.expires_hours <= 8760:
                parser.error("Provide an identifier up to 64 characters, a student year, and expiry between 1 and 8760 hours.")
            model, field = (Student, Student.roll_no) if args.role == "student" else (Mentor, Mentor.username)
            existing = db.query(model).filter(func.lower(func.trim(field)) == roll.lower()).all()
            if len(existing) > 1 or any(row.clerk_user_id for row in existing):
                parser.error("This identifier already has a linked or ambiguous profile.")
            code = secrets.token_urlsafe(24)
            now = int(time.time())
            grant = EnrollmentCode(role=args.role, code_hash=code_hash(code), roll_no=roll, year=year,
                                   created_at=now, expires_at=now + args.expires_hours * 3600)
            db.add(grant)
            db.commit()
            print(f"Enrollment ID: {grant.id}\nPortal: {args.role}\nIdentifier: {roll}\nYear: {year}\nCode: {code}\nExpires in: {args.expires_hours} hours")
            print("Send this code privately. It is displayed only now; PostgreSQL stores its hash.")
        else:
            grant = db.query(EnrollmentCode).filter(EnrollmentCode.id == args.id).with_for_update().first()
            if not grant:
                parser.error("Enrollment ID not found.")
            grant.revoked_at = int(time.time())
            db.commit()
            print("Enrollment revoked.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Enrollment command failed: {type(error).__name__}")
        raise SystemExit(1)


def redeem_mentor(db, subject, mentor_name, code):
    name = mentor_name.strip()
    if db.bind.dialect.name == "postgresql":
        for key in sorted(("enrollment-subject:" + subject, "enrollment-mentor:" + name.lower())):
            db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
    if db.query(Student).filter(Student.clerk_user_id == subject).first() or db.query(Mentor).filter(Mentor.clerk_user_id == subject).first():
        raise HTTPException(409, "This Clerk account already has a profile.")
    grant = db.query(EnrollmentCode).filter(EnrollmentCode.code_hash == code_hash(code)).with_for_update().first()
    now = int(time.time())
    if (not grant or grant.role != "mentor" or grant.used_at is not None or grant.revoked_at is not None
            or grant.expires_at <= now or grant.roll_no.strip().lower() != name.lower()):
        raise HTTPException(403, "Mentor enrollment code is invalid, expired, used, revoked, or does not match the mentor name.")
    profiles = db.query(Mentor).filter(func.lower(func.trim(Mentor.username)) == name.lower()).with_for_update().all()
    if len(profiles) > 1 or any(profile.clerk_user_id for profile in profiles):
        raise HTTPException(409, "This mentor name already has a linked or ambiguous profile.")
    profile = profiles[0] if profiles else Mentor(username=grant.roll_no)
    profile.clerk_user_id = subject
    db.add(profile)
    grant.used_at = now
    grant.used_by_clerk_user_id = subject
    db.flush()
    return profile
