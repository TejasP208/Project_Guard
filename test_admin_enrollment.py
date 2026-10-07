"""Enrollment and administrator authorization checks using an isolated database."""
import os
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import main
from enrollment import code_hash, redeem_mentor, redeem_student
from models import Base, EnrollmentCode, Mentor, Student


class AdminEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.request = Request({'type': 'http', 'headers': []})
        self.request.state.clerk_user_id = 'admin'
        self.env = patch.dict(os.environ, {'ENROLLMENT_ADMIN_CLERK_USER_IDS': 'admin', 'CLERK_SECRET_KEY': 'sk_test_fixture'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.db_patch = patch.object(main, 'SessionLocal', self.sessions)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.engine.dispose)

    def issue(self, role='mentor'):
        return main.issue_enrollment(main.AdminEnrollmentRequest(role=role, roll_no=' Mentor1 ', year='Y1'), self.request)

    def test_mentor_code_required_and_bound_to_role_name_and_single_use(self):
        grant = self.issue()
        with self.sessions() as db:
            for name in ('Other mentor',):
                with self.assertRaises(HTTPException):
                    redeem_mentor(db, 'user1', name, grant['code'])
            with self.assertRaises(HTTPException):
                redeem_student(db, 'user1', 'Mentor1', 'Y1', grant['code'])
            profile = redeem_mentor(db, 'user1', 'mentor1', grant['code'])
            self.assertEqual(profile.username, 'Mentor1')
            db.commit()
            with self.assertRaises(HTTPException):
                redeem_mentor(db, 'user2', 'mentor1', grant['code'])

    def test_expired_and_revoked_mentor_grants_rejected(self):
        for state in ('expired', 'revoked'):
            grant = self.issue()
            with self.sessions() as db:
                row = db.get(EnrollmentCode, grant['id'])
                if state == 'expired': row.expires_at = int(time.time()) - 1
                else: row.revoked_at = int(time.time())
                db.commit()
                with self.assertRaises(HTTPException):
                    redeem_mentor(db, 'user1', 'mentor1', grant['code'])

    def test_admin_only_and_student_year_required(self):
        self.request.state.clerk_user_id = 'outsider'
        for action in (lambda: self.issue(), lambda: main.list_admin_accounts(self.request),
                       lambda: main.delete_admin_account('mentor', 1, self.request)):
            with self.assertRaises(HTTPException) as failure: action()
            self.assertEqual(failure.exception.status_code, 403)
        self.request.state.clerk_user_id = 'admin'
        with self.assertRaises(HTTPException):
            main.issue_enrollment(main.AdminEnrollmentRequest(roll_no='S1', year=' '), self.request)

    def test_admin_deletes_both_roles_and_preserves_profile_on_clerk_failure(self):
        with self.sessions() as db:
            db.add_all([Student(id=1, roll_no='S1', clerk_user_id='student1'), Mentor(id=1, username='M1', clerk_user_id='mentor1')])
            db.commit()
        with patch.object(main, 'Clerk') as clerk:
            clerk.return_value.users.delete.side_effect = RuntimeError('unavailable')
            with self.assertRaises(HTTPException): main.delete_admin_account('mentor', 1, self.request)
            with self.sessions() as db: self.assertIsNotNone(db.get(Mentor, 1))
            clerk.return_value.users.delete.side_effect = None
            for role, subject in (('student', 'student1'), ('mentor', 'mentor1')):
                main.delete_admin_account(role, 1, self.request)
                clerk.return_value.users.delete.assert_called_with(user_id=subject, timeout_ms=10_000)
        with self.sessions() as db:
            self.assertIsNone(db.get(Student, 1))
            self.assertIsNone(db.get(Mentor, 1))

    def test_unlinked_legacy_profile_can_be_deleted_without_clerk_configuration(self):
        with self.sessions() as db:
            db.add(Mentor(id=1, username='Legacy mentor'))
            db.commit()
        with patch.dict(os.environ, {'CLERK_SECRET_KEY': ''}), patch.object(main, 'Clerk') as clerk:
            main.delete_admin_account('mentor', 1, self.request)
            clerk.assert_not_called()
        with self.sessions() as db:
            self.assertIsNone(db.get(Mentor, 1))

    def test_admin_cannot_delete_own_profile(self):
        with self.sessions() as db:
            db.add(Mentor(id=1, username='Administrator', clerk_user_id='admin'))
            db.commit()
        with patch.object(main, 'Clerk') as clerk:
            with self.assertRaises(HTTPException) as failure:
                main.delete_admin_account('mentor', 1, self.request)
            self.assertEqual(failure.exception.status_code, 409)
            clerk.assert_not_called()


if __name__ == '__main__': unittest.main()
