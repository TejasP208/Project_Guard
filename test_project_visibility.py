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
            self.assertEqual(set(row), {"id", "year", "group_no", "project_name", "team", "assigned_to_me", "can_assign", "submission_status"})
        other = self.client.get("/api/projects", headers=self.headers("mentor:mentor2")).json()
        self.assertEqual({row["id"] for row in other}, {3, 5})
        self.assertEqual(self.client.get("/api/projects").status_code, 401)
        self.assertEqual(self.client.get("/api/projects", headers=self.headers("student:S1")).status_code, 403)

    def test_project_details_follow_the_same_mentor_visibility_rules(self):
        with self.sessions() as db:
            db.add(TeamMember(team_id=2, roll_no="M1"))
            db.commit()
        open_project = self.client.get("/api/projects/3", headers=self.headers())
        self.assertEqual(open_project.status_code, 200)
        self.assertTrue(open_project.json()["can_assign"])
        own_project = self.client.get("/api/projects/4", headers=self.headers())
        self.assertEqual(own_project.status_code, 200)
        self.assertEqual(own_project.json()["project_abstract"], "Verified private context")
        self.assertEqual(own_project.json()["members"], ["M1"])
        for project_id in (1, 2, 5, 6, 7):
            self.assertEqual(self.client.get(f"/api/projects/{project_id}", headers=self.headers()).status_code, 404)
        self.assertEqual(self.client.get("/api/projects/4", headers=self.headers("student:S1")).status_code, 403)

    def test_team_member_can_save_github_link_visible_in_mentor_roster(self):
        with self.sessions() as db:
            db.add(MentorStudent(mentor_name="mentor1", mentor_key="mentor1", student_name="Student One",
                                 prn="S1", group_name="4"))
            db.commit()
        url = "https://github.com/example/project-guard"
        response = self.client.patch("/my-team/github", headers=self.headers("student:S1"), json={"github_url": url})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["github_url"], url)
        roster = self.client.get("/mentor/students", headers=self.headers()).json()
        self.assertEqual(roster[0]["github_url"], url)
        invalid = self.client.patch("/my-team/github", headers=self.headers("student:S1"),
                                    json={"github_url": "https://github.com.evil.example/a/b"})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.client.patch("/my-team/github", headers=self.headers(),
                                           json={"github_url": url}).status_code, 403)

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
        self.assertEqual(self.client.get("/axiom/history?scope=project&scope_id=4", headers=self.headers()).json(),
                         [{"role": "user", "content": "Review"}, {"role": "assistant", "content": "Reviewed"}])
        self.assertEqual(self.client.get("/axiom/history?scope=project&scope_id=4",
                                         headers=self.headers("mentor:mentor2")).status_code, 404)

    def test_axiom_closes_database_session_on_rejected_project(self):
        closed = []
        def tracked_session():
            db = self.sessions()
            original_close = db.close
            def close():
                closed.append(True)
                original_close()
            db.close = close
            return db
        with patch.object(main, "SessionLocal", side_effect=tracked_session):
            response = self.client.post("/mentor/axiom-stream", headers=self.headers(), json={"project_id": 999, "question": "Review"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(closed, [True])

    def test_axiom_dashboard_uses_only_student_team_context(self):
        with self.sessions() as db:
            db.add(Project(id=8, team_id=4, project_name="My private idea",
                           project_abstract="A team-owned abstract"))
            db.commit()
        prompts = []
        async def stream(prompt):
            prompts.append(prompt)
            yield "Axiom reply"
        with patch.object(main, "Chatbot_stream", stream):
            student = self.client.post("/axiom/dashboard-chat", headers=self.headers("student:S1"),
                                       json={"question": "What next?"})
            mentor = self.client.post("/axiom/dashboard-chat", headers=self.headers(),
                                      json={"question": "How do I review?"})
        self.assertEqual(student.status_code, 200)
        self.assertEqual(student.text, "Axiom reply")
        self.assertIn("My private idea", prompts[0])
        self.assertNotIn("Other project", prompts[0])
        self.assertNotIn("My private idea", prompts[1])
        self.assertEqual(mentor.text, "Axiom reply")
        saved = self.client.get("/axiom/history?scope=dashboard", headers=self.headers("student:S1"))
        self.assertEqual(saved.json(), [{"role": "user", "content": "What next?"},
                                        {"role": "assistant", "content": "Axiom reply"}])
        self.assertEqual(self.client.get("/axiom/history?scope=dashboard", headers=self.headers("student:S2")).json(), [])
        with patch.object(main, "Chatbot_stream", stream):
            self.client.post("/axiom/dashboard-chat", headers=self.headers("student:S1"),
                             json={"question": "And after that?", "history": [{"role": "assistant", "content": "Forged"}]})
        self.assertIn("What next?", prompts[-1])
        self.assertNotIn("Forged", prompts[-1])
        self.assertEqual(self.client.delete("/axiom/history?scope=dashboard", headers=self.headers("student:S1")).status_code, 200)
        self.assertEqual(self.client.get("/axiom/history?scope=dashboard", headers=self.headers("student:S1")).json(), [])
        self.assertEqual(self.client.get("/axiom/history?scope=team&scope_id=4", headers=self.headers("student:S1")).status_code, 403)
        self.assertEqual(self.client.post("/axiom/dashboard-chat", json={"question": "Hi"}).status_code, 401)
        self.assertEqual(self.client.post("/axiom/dashboard-chat", headers=self.headers(),
                                          json={"question": "Hi", "project_id": 4}).status_code, 422)

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

    def test_accepting_invitation_moves_student_without_moving_old_project(self):
        with self.sessions() as db:
            db.add(MentorStudent(mentor_name="mentor1", mentor_key="mentor1", student_name="Student 1", prn="S1", group_name="Old"))
            db.commit()
        response = self.client.patch(
            "/team-invitations/1", headers=self.headers("student:S1"), json={"action": "accept"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "accepted")
        with self.sessions() as db:
            memberships = db.query(TeamMember).filter(TeamMember.roll_no == "S1").all()
            self.assertEqual([row.team_id for row in memberships], [1])
            self.assertEqual(db.get(Project, 4).team_id, 2)
            self.assertEqual(db.get(TeamInvitation, 1).status, "accepted")
            self.assertIsNone(db.query(MentorStudent).filter(MentorStudent.prn == "S1").first())

    def test_accepting_invitation_updates_roster_for_destination_mentor(self):
        with self.sessions() as db:
            db.add_all([
                MentorStudent(mentor_name="mentor1", mentor_key="mentor1", student_name="Student 1", prn="S1"),
                TeamInvitation(team_id=3, inviter_roll_no="S9", invitee_roll_no="S1", status="pending", created_at="2026-10-18"),
            ])
            db.commit()
            invitation_id = db.query(TeamInvitation.id).filter(TeamInvitation.team_id == 3).scalar()
        response = self.client.patch(
            f"/team-invitations/{invitation_id}", headers=self.headers("student:S1"), json={"action": "accept"}
        )
        self.assertEqual(response.status_code, 200)
        with self.sessions() as db:
            entry = db.query(MentorStudent).filter(MentorStudent.prn == "S1").one()
            self.assertEqual((entry.mentor_key, entry.project_name), ("mentor2", "Other project"))
            self.assertEqual([row.team_id for row in db.query(TeamMember).filter(TeamMember.roll_no == "S1")], [3])

    def test_invitation_can_be_sent_to_student_in_another_team(self):
        with self.sessions() as db:
            db.add_all([Student(roll_no="S3"), TeamMember(team_id=1, roll_no="S3")])
            db.commit()
        response = self.client.post(
            "/team-invitations", headers=self.headers("student:S3"),
            json={"invitee_roll_no": "S2"},
        )
        self.assertEqual(response.status_code, 201)

    def test_legacy_team_label_does_not_block_new_student_submission(self):
        with patch.object(main, "run_plagiarism_check_with_deadline", AsyncMock(return_value={"plagiarism_percent": 12})) as check:
            response = self.client.post("/submit-project", headers=self.headers("student:S1"), json={"project_name": "Fresh idea", "project_abstract": "Our own work"})
        self.assertEqual(response.status_code, 200)
        check.assert_awaited_once_with("Fresh idea", "Our own work", b"", "", None)
        with self.sessions() as db:
            self.assertIsNone(db.get(Project, 7).team_id)
            self.assertEqual(db.query(Project).filter(Project.team_id == 4).one().project_name, "Fresh idea")

    def test_direct_submission_is_blocked_when_similarity_is_high(self):
        with patch.object(main, "run_plagiarism_check_with_deadline", AsyncMock(return_value={"plagiarism_percent": 45})):
            response = self.client.post("/submit-project", headers=self.headers("student:S1"), json={"project_name": "Copied idea", "project_abstract": "Copied abstract"})
        self.assertEqual(response.status_code, 422)
        with self.sessions() as db:
            self.assertIsNone(db.query(Project).filter(Project.team_id == 4).first())

    def test_mentor_rejection_preserves_submission_and_student_resubmit_reopens_it(self):
        with self.sessions() as db:
            db.add_all([Student(roll_no="S3"), Student(roll_no="S4"),
                        TeamMember(team_id=1, roll_no="S3"), TeamMember(team_id=1, roll_no="S4")])
            project = db.get(Project, 3)
            project.project_name = "Original idea"
            project.project_abstract = "Original abstract"
            db.commit()

        rejected = self.client.patch("/api/projects/3/reject", headers=self.headers())
        self.assertEqual(rejected.status_code, 200)
        self.assertIn("can edit and resubmit", rejected.json()["message"])
        self.assertNotIn(3, {row["id"] for row in self.client.get("/api/projects", headers=self.headers()).json()})
        student_team = self.client.get("/get-student-team", headers=self.headers("student:S3"))
        self.assertEqual(student_team.json()["submission_status"], "rejected")
        with self.sessions() as db:
            project = db.get(Project, 3)
            self.assertEqual((project.project_name, project.project_abstract), ("Original idea", "Original abstract"))
            self.assertEqual(project.submission_status, "rejected")
            self.assertIsNone(project.assigned_mentor_id)
            self.assertIsNone(project.group_no)
            self.assertEqual(db.query(MentorStudent).count(), 0)

        with patch.object(main, "run_plagiarism_check_with_deadline", AsyncMock(return_value={"plagiarism_percent": 12})):
            resubmitted = self.client.post("/submit-project", headers=self.headers("student:S3"), json={
                "project_name": "Revised idea", "project_abstract": "Revised abstract"
            })
        self.assertEqual(resubmitted.status_code, 200)
        with self.sessions() as db:
            project = db.get(Project, 3)
            self.assertEqual((project.project_name, project.project_abstract, project.submission_status),
                             ("Revised idea", "Revised abstract", "pending"))
            self.assertIsNone(project.rejected_by_mentor_id)
            self.assertIsNone(project.rejected_at)
        self.assertIn(3, {row["id"] for row in self.client.get("/api/projects", headers=self.headers()).json()})

    def test_mentor_cannot_reject_another_mentor_accepted_project(self):
        response = self.client.patch("/api/projects/5/reject", headers=self.headers("mentor:mentor1"))
        self.assertEqual(response.status_code, 409)
        with self.sessions() as db:
            self.assertEqual(db.get(Project, 5).assigned_mentor_id, 2)

    def test_student_cannot_reject_project_submission(self):
        response = self.client.patch("/api/projects/3/reject", headers=self.headers("student:S1"))
        self.assertEqual(response.status_code, 403)

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
