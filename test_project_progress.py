"""Team scoped document and progress workflow checks."""
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from models import Base, Mentor, MentorReview, Project, ProjectDocument, Student, SubmissionCheck, Team, TeamMember


class ProjectProgressTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        def subject(request):
            value = request.headers.get("x-test-subject")
            if not value:
                raise HTTPException(401, "Authentication required")
            return value
        def profile(identity):
            role, user = identity.split(":", 1)
            return {"role": role, "identifier": user, "year": "3"}
        self.patches = [patch.object(main, "SessionLocal", self.sessions), patch.object(main, "engine", self.engine),
                        patch.object(main, "require_clerk_user_id", subject),
                        patch.object(main, "resolve_profile_for_clerk_user_id", profile),
                        patch.object(main, "rate_limit_retry_after", return_value=None),
                        patch.object(main, "run_plagiarism_check_with_deadline", new_callable=AsyncMock,
                                     return_value={"plagiarism_percent": 0})]
        for item in self.patches:
            item.start()
        with self.sessions() as db:
            db.add_all([Mentor(id=1, username="Rao"), Mentor(id=2, username="Other"),
                        Student(roll_no="S1", year="3"), Student(roll_no="S2", year="3"),
                        Team(id=1, team_name="Group 1", sheet_group_no="1", year="3"),
                        TeamMember(team_id=1, roll_no="S1"), TeamMember(team_id=1, roll_no="S2")])
            db.commit()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()

    def call(self, method, path, identity="student:S1", **kwargs):
        return self.client.request(method, path, headers={"x-test-subject": identity}, **kwargs)

    def checked_submission(self, title, abstract, content=b"Garden AI uses images to identify plants."):
        document = {"file": ("idea.txt", content, "text/plain")}
        checked = self.call("POST", "/check-plagiarism", data={"title": title, "description": abstract}, files=document)
        self.assertEqual(checked.status_code, 200, checked.text)
        return self.call("POST", "/submit-project-with-file",
                         data={"project_name": title, "project_abstract": abstract, "check_token": checked.json()["check_token"]},
                         files=document)

    def test_idea_file_is_retained_and_shared_by_team(self):
        response = self.checked_submission("Garden AI", "Identify plants")
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as db:
            document = db.query(ProjectDocument).one()
            self.assertEqual(document.slot, "project_idea")
            self.assertEqual(document.content, b"Garden AI uses images to identify plants.")
        progress = self.call("GET", "/student/project-progress", identity="student:S2").json()
        self.assertEqual(progress["documents"]["project_idea"], "idea.txt")
        self.assertEqual(progress["project_name"], "Garden AI")
        self.assertEqual(progress["project_abstract"], "Identify plants")
        self.assertEqual({member["roll_no"] for member in progress["members"]}, {"S1", "S2"})
        team = self.call("GET", "/get-student-team", identity="student:S2").json()
        self.assertEqual(team["project_name"], "Garden AI")
        self.assertEqual(team["project_abstract"], "Identify plants")
        self.assertEqual({member["roll_no"] for member in team["member_details"]}, {"S1", "S2"})

    def test_check_required_inputs_and_fifty_percent_boundary(self):
        files = {"file": ("idea.txt", b"Detailed project idea", "text/plain")}
        self.assertEqual(self.call("POST", "/check-plagiarism", data={"title": "Idea", "description": " "}, files=files).status_code, 422)
        self.assertEqual(self.call("POST", "/check-plagiarism", data={"title": "Idea", "description": "Abstract"}).status_code, 422)
        self.assertEqual(self.call("POST", "/submit-project-with-file",
                                   data={"project_name": "Idea", "project_abstract": "Abstract"}, files=files).status_code, 422)
        main.run_plagiarism_check_with_deadline.return_value = {"plagiarism_percent": 50}
        at_limit = self.call("POST", "/check-plagiarism", data={"title": "Idea", "description": "Abstract"}, files=files)
        self.assertEqual(at_limit.status_code, 200)
        self.assertTrue(at_limit.json()["can_submit"])
        self.assertIn("check_token", at_limit.json())
        main.run_plagiarism_check_with_deadline.return_value = {"plagiarism_percent": 50.01}
        above_limit = self.call("POST", "/check-plagiarism", data={"title": "Idea", "description": "Abstract"}, files=files)
        self.assertFalse(above_limit.json()["can_submit"])
        self.assertNotIn("check_token", above_limit.json())

    def test_check_is_bound_to_student_content_and_one_submission(self):
        files = {"file": ("idea.txt", b"Detailed project idea", "text/plain")}
        checked = self.call("POST", "/check-plagiarism", data={"title": "Idea", "description": "Abstract"}, files=files)
        token = checked.json()["check_token"]
        data = {"project_name": "Idea", "project_abstract": "Abstract", "check_token": token}
        self.assertEqual(self.call("POST", "/submit-project-with-file", identity="student:S2", data=data, files=files).status_code, 422)
        self.assertEqual(self.call("POST", "/submit-project-with-file", data={**data, "project_abstract": "Changed"}, files=files).status_code, 422)
        self.assertEqual(self.call("POST", "/submit-project-with-file", data=data,
                                   files={"file": ("idea.txt", b"Changed document", "text/plain")}).status_code, 422)
        self.assertEqual(self.call("POST", "/submit-project-with-file", data=data, files=files).status_code, 200)
        self.assertEqual(self.call("POST", "/submit-project-with-file", data=data, files=files).status_code, 422)

    def test_expired_and_invalid_scores_do_not_allow_submission(self):
        files = {"file": ("idea.txt", b"Detailed project idea", "text/plain")}
        main.run_plagiarism_check_with_deadline.return_value = {"plagiarism_percent": float("nan")}
        invalid = self.call("POST", "/check-plagiarism", data={"title": "Idea", "description": "Abstract"}, files=files)
        self.assertEqual(invalid.status_code, 503)
        main.run_plagiarism_check_with_deadline.return_value = {"plagiarism_percent": 10}
        checked = self.call("POST", "/check-plagiarism", data={"title": "Idea", "description": "Abstract"}, files=files)
        with self.sessions() as db:
            receipt = db.query(SubmissionCheck).one()
            receipt.expires_at = 0
            db.commit()
        self.assertEqual(self.call("POST", "/submit-project-with-file",
                                   data={"project_name": "Idea", "project_abstract": "Abstract",
                                         "check_token": checked.json()["check_token"]}, files=files).status_code, 422)

    def test_review_and_topic_decisions_require_assigned_mentor(self):
        with self.sessions() as db:
            db.add(Project(team_id=1, project_name="Old", assigned_mentor_id=1, submission_status="accepted"))
            db.commit()
        bypass = self.call("POST", "/submit-project", json={"project_name": "New", "project_abstract": "New abstract"})
        self.assertEqual(bypass.status_code, 422)
        self.assertEqual(self.checked_submission("New", "New abstract").status_code, 409)
        upload_request = lambda slot: self.call("POST", f"/student/project-documents/{slot}",
                                                files={"file": ("review.txt", b"Our first review notes.", "text/plain")})
        self.assertIsNone(self.call("GET", "/student/project-progress").json()["active_review"])
        self.assertEqual(upload_request("project_reviews1").status_code, 409)
        with self.sessions() as db:
            db.add_all([
                MentorReview(mentor_name="Rao", mentor_key="rao", team_id=1, group_name="1",
                             review_type="Progress Review-1", review_date="2026-11-01", review_time="10:00",
                             status="scheduled", created_at="2026-10-20"),
                MentorReview(mentor_name="Rao", mentor_key="rao", team_id=1, group_name="1",
                             review_type="Progress Review-2", review_date="2026-12-01", review_time="10:00",
                             status="scheduled", created_at="2026-10-20"),
            ])
            db.commit()
        self.assertEqual(self.call("GET", "/student/project-progress").json()["active_review"]["slot"], "project_reviews1")
        self.assertEqual(upload_request("project_reviews2").status_code, 409)
        upload = upload_request("project_reviews1")
        self.assertEqual(upload.status_code, 200, upload.text)
        self.assertEqual(self.call("PATCH", "/mentor/teams/1/reviews/1/complete", identity="mentor:Other").status_code, 404)
        self.assertEqual(self.call("PATCH", "/mentor/teams/1/reviews/1/complete", identity="mentor:Rao").status_code, 200)
        self.assertEqual(self.call("GET", "/student/project-progress").json()["active_review"]["slot"], "project_reviews2")
        change = self.call("POST", "/student/topic-change-requests", json={"proposed_title": "New", "proposed_abstract": "New abstract", "reason": "Better scope"})
        self.assertEqual(change.status_code, 200, change.text)
        change_id = change.json()["id"]
        self.assertEqual(self.call("PATCH", f"/mentor/topic-change-requests/{change_id}/accepted", identity="mentor:Other").status_code, 404)
        self.assertEqual(self.call("PATCH", f"/mentor/topic-change-requests/{change_id}/accepted", identity="mentor:Rao").status_code, 200)
        progress = self.call("GET", "/student/project-progress").json()
        self.assertEqual(progress["project_name"], "New")
        self.assertEqual(progress["project_abstract"], "New abstract")
        self.assertEqual(progress["review1"], "not_submitted")
        self.assertNotIn("project_reviews1", progress["documents"])

    def test_mentor_project_chat_uses_selected_team_and_returns_sources(self):
        with self.sessions() as db:
            db.add(Project(team_id=1, project_name="Garden AI", project_abstract="Recognizes plants"))
            db.commit()
        passage = {"document_id": 5, "slot": "project_idea", "filename": "idea.txt",
                   "chunk_number": 1, "text": "The app recognizes plants from photographs."}
        with patch.object(main, "index_missing_for_team"), \
             patch.object(main, "retrieve_team_passages", return_value=[passage]) as retrieve, \
             patch.object(main, "answer_project_question", new_callable=AsyncMock,
                          return_value="It recognizes plants from photos [1]."):
            response = self.call("POST", "/mentor/project-chat", identity="mentor:Rao",
                                 json={"team_id": 1, "question": "What does it do?"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sources"][0]["filename"], "idea.txt")
        self.assertNotIn("text", response.json()["sources"][0])
        self.assertEqual(retrieve.call_args.args[:2], (1, "What does it do?"))
        history = self.call("GET", "/axiom/history?scope=team&scope_id=1", identity="mentor:Rao")
        self.assertEqual(history.json(), [{"role": "user", "content": "What does it do?"},
                                          {"role": "assistant", "content": "It recognizes plants from photos [1]."}])
        self.assertEqual(self.call("GET", "/axiom/history?scope=team&scope_id=1", identity="mentor:Other").json(), [])
        self.assertEqual(self.call("GET", "/axiom/history?scope=team&scope_id=1", identity="student:S1").status_code, 403)
        self.assertEqual(self.call("POST", "/mentor/project-chat", identity="student:S1",
                                   json={"team_id": 1, "question": "What does it do?"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
