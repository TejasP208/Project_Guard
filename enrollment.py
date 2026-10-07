"""Student enrollment grants issued by operators with private backend access."""
import argparse
import hashlib
import secrets
import time

from fastapi import HTTPException
from sqlalchemy import func, text
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
    if (not grant or grant.used_at is not None or grant.revoked_at is not None
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
    issue.add_argument("--roll-no", required=True)
    issue.add_argument("--year", required=True)
    issue.add_argument("--expires-hours", type=int, default=168)
    revoke = commands.add_parser("revoke")
    revoke.add_argument("--id", type=int, required=True)
    args = parser.parse_args()
    from database import SessionLocal, engine
    # Also usable before starting FastAPI; create only this additive table.
    EnrollmentCode.__table__.create(engine, checkfirst=True)
    with SessionLocal() as db:
        if args.command == "issue":
            roll, year = args.roll_no.strip(), args.year.strip()
            if not roll or not year or len(roll) > 64 or len(year) > 64 or not 1 <= args.expires_hours <= 8760:
                parser.error("Provide nonblank roll/year up to 64 characters and expiry between 1 and 8760 hours.")
            existing = db.query(Student).filter(func.lower(func.trim(Student.roll_no)) == roll.lower()).all()
            if len(existing) > 1 or any(row.clerk_user_id for row in existing):
                parser.error("This roll number already has a linked or ambiguous profile.")
            code = secrets.token_urlsafe(24)
            now = int(time.time())
            grant = EnrollmentCode(code_hash=code_hash(code), roll_no=roll, year=year,
                                   created_at=now, expires_at=now + args.expires_hours * 3600)
            db.add(grant)
            db.commit()
            print(f"Enrollment ID: {grant.id}\nRoll number: {roll}\nYear: {year}\nCode: {code}\nExpires in: {args.expires_hours} hours")
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
