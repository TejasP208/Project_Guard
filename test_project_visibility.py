"""API visibility/response tests with trusted profiles and an isolated database."""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from legacy_projects import legacy_inventory, reconcile_projects
from models import Base, EnrollmentCode, Mentor, MentorStudent, Project, Student, Team, TeamInvitation, TeamMember
from mentor_roster import mentor_key


class ProjectVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.patches = [
            patch.object(main, "SessionLocal", self.sessions),
            patch.object(main, "engine", self.engine),
            patch.object(main, "require_clerk_user_id", self.subject),
            patch.object(main, "resolve_profile_for_clerk_user_id", self.profile),
            patch.object(main, "rate_limit_retry_after", return_value=None),
        ]
        for replacement in self.patches:
            replacement.start()
        self.client = TestClient(main.app)
        with self.sessions() as db:
            db.add_all([Mentor(id=1, username="mentor1"), Mentor(id=2, username="mentor2")])
            db.add_all([Student(roll_no="S1"), Student(roll_no="S2")])
            db.add_all([Team(id=i, team_name="Same label" if i == 4 else f"Team {i}", team_code=f"CODE{i}") for i in range(1, 5)])
            db.add_all([
                Project(id=1, project_name="Legacy public", project_abstract="Historical abstract"),
                Project(id=2, project_name="Legacy assigned", assigned_mentor_id=1),
                Project(id=3, project_name="Open idea", team_id=1),
                Project(id=4, project_name="Own project", project_abstract="Verified private context", team_id=2, assigned_mentor_id=1),
                Project(id=5, project_name="Other project", team_id=3, assigned_mentor_id=2),
                Project(id=6, project_name="Orphan", team_id=999),
                Project(id=7, project_name="Unlinked same label", team_name="Same label"),
                TeamMember(team_id=4, roll_no="S1"), TeamMember(team_id=4, roll_no="S2"),
                TeamInvitation(team_id=1, inviter_roll_no="S3", invitee_roll_no="S1", status="pending", created_at="2026-10-07"),
            ])
            db.commit()

    def tearDown(self):
        self.client.close()
        for replacement in reversed(self.patches):
            replacement.stop()
        self.engine.dispose()

    @staticmethod
    def subject(request):
        value = request.headers.get("x-test-subject")
        if not value:
            raise HTTPException(401, "Authentication required.")
        return value

    @staticmethod
    def profile(subject):
        role, identifier = subject.split(":", 1)
        return {"role": role, "identifier": identifier, "year": None}

    def headers(self, subject="mentor:mentor1"):
        return {"x-test-subject": subject}

    def test_project_list_excludes_legacy_orphans_and_other_assignments(self):
        response = self.client.get("/api/projects", headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["id"] for row in response.json()}, {3, 4})
        for row in response.json():
            self.assertEqual(set(row), {"id", "year", "group_no", "project_name", "team", "assigned_to_me", "can_assign"})
        other = self.client.get("/api/projects", headers=self.headers("mentor:mentor2")).json()
        self.assertEqual({row["id"] for row in other}, {3, 5})
        self.assertEqual(self.client.get("/api/projects").status_code, 401)
        self.assertEqual(self.client.get("/api/projects", headers=self.headers("student:S1")).status_code, 403)

    def test_axiom_rejects_legacy_orphan_other_owner_and_spoofed_context(self):
        for project_id in (1, 2, 5, 6, 7):
            response = self.client.post("/mentor/axiom-stream", headers=self.headers(), json={"project_id": project_id, "question": "Review"})
            self.assertEqual(response.status_code, 404)
        response = self.client.post("/mentor/axiom-stream", headers=self.headers(), json={"project_id": 4, "question": "Review", "project_abstract": "Forged"})
        self.assertEqual(response.status_code, 422)
        prompts = []
        async def stream(prompt):
            prompts.append(prompt)
            yield "Reviewed"
        with patch.object(main, "Chatbot_stream", stream):
            response = self.client.post("/mentor/axiom-stream", headers=self.headers(), json={"project_id": 4, "question": "Review"})
        self.assertEqual(response.text, "Reviewed")
        self.assertIn("Verified private context", prompts[0])

    def test_pending_invitation_omits_join_code_and_profile_link_omits_subject(self):
        invitations = self.client.get("/team-invitations", headers=self.headers("student:S1")).json()
        self.assertEqual(set(invitations[0]), {"id", "team_name", "inviter_roll_no"})
        import time
        from enrollment import code_hash
        with self.sessions() as db:
            db.add(EnrollmentCode(code_hash=code_hash("fixture-code"), roll_no="NEW", year="Y1", created_at=int(time.time()), expires_at=int(time.time()) + 3600))
            db.commit()
        response = self.client.post("/api/profile/link", headers=self.headers("student:new"), json={"role": "student", "roll_no": "NEW", "year": "Y1", "enrollment_code": "fixture-code"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("clerk_user_id", response.json())

    def test_legacy_team_label_does_not_block_new_student_submission(self):
        response = self.client.post("/submit-project", headers=self.headers("student:S1"), json={"project_name": "Fresh idea", "project_abstract": "Our own work"})
        self.assertEqual(response.status_code, 200)
        with self.sessions() as db:
            self.assertIsNone(db.get(Project, 7).team_id)
            self.assertEqual(db.query(Project).filter(Project.team_id == 4).one().project_name, "Fresh idea")

    def test_plagiarism_returns_only_summary_and_denies_mentor(self):
        check = AsyncMock(return_value={
            "plagiarism_percent": 12, "risk_level": "Low",
            "matched_project": "Private legacy title", "matched_group": 42,
            "top_3_matches": [{"project_id": 5}], "document_text_truncated": True,
        })
        with patch.object(main, "run_plagiarism_check_with_deadline", check):
            response = self.client.post("/check-plagiarism", headers=self.headers("student:S1"), data={"title": "Idea"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"plagiarism_percent": 12, "risk_level": "Low", "document_text_truncated": True})
            self.assertEqual(self.client.post("/check-plagiarism", headers=self.headers()).status_code, 403)

    def test_stale_roster_does_not_leak_project_through_lists_or_dashboard(self):
        with self.sessions() as db:
            db.add_all([TeamMember(team_id=3, roll_no="OTHER"), Student(roll_no="OTHER"),
                        MentorStudent(mentor_name="mentor1", mentor_key=mentor_key("mentor1"), student_name="Stale member", prn="OTHER", project_name="Other project")])
            db.commit()
        for path in ("/api/students", "/mentor/students"):
            self.assertEqual(self.client.get(path, headers=self.headers()).json(), [])
        dashboard = self.client.get("/mentor/dashboard", headers=self.headers()).json()
        self.assertEqual(dashboard["assigned_students"], 0)
        self.assertEqual(dashboard["active_projects"], 0)

    def test_migration_preview_preserves_rows_and_commit_scopes_visibility(self):
        mapping = [{"project_id": 1, "team_id": 4, "mentor_id": 1}]
        with self.sessions() as db:
            self.assertEqual({row["project_id"] for row in legacy_inventory(db)}, {1, 2, 6, 7})
            reconcile_projects(db, mapping)
            db.rollback()
            self.assertIsNone(db.get(Project, 1).team_id)
            self.assertEqual(db.query(MentorStudent).count(), 0)
            reconcile_projects(db, mapping)
            db.commit()
            self.assertEqual(db.get(Project, 1).project_abstract, "Historical abstract")
            self.assertEqual(db.query(MentorStudent).count(), 2)
        own = self.client.get("/api/projects", headers=self.headers()).json()
        other = self.client.get("/api/projects", headers=self.headers("mentor:mentor2")).json()
        self.assertIn(1, {row["id"] for row in own})
        self.assertNotIn(1, {row["id"] for row in other})

    def test_migration_rejects_conflicts_and_validates_whole_batch(self):
        with self.sessions() as db:
            for mapping in (
                [{"project_id": 1, "team_id": 1, "mentor_id": 1}],
                [{"project_id": 2, "team_id": 4, "mentor_id": 2}],
                [{"project_id": 1, "team_id": 4, "mentor_id": 1}, {"project_id": 2, "team_id": 1, "mentor_id": 1}],
                [{"project_id": 1, "team_id": 4, "mentor_id": 1}, {"project_id": 7, "team_id": 4, "mentor_id": 1}],
            ):
                with self.assertRaises(ValueError):
                    reconcile_projects(db, mapping)
                db.rollback()
                self.assertIsNone(db.get(Project, 1).team_id)
            db.add(MentorStudent(mentor_name="mentor2", mentor_key=mentor_key("mentor2"), student_name="Student", prn="S1"))
            db.commit()
            with self.assertRaises(ValueError):
                reconcile_projects(db, [{"project_id": 1, "team_id": 4, "mentor_id": 1}])


if __name__ == "__main__":
    unittest.main()
