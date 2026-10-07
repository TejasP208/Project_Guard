"""Roster, review and invitation regressions with trusted test profiles."""
from io import BytesIO
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import main
from models import Base, Mentor, Project, Student, Team, TeamMember

def workbook_bytes(rows):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()

class MentorRosterTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        def subject(request):
            identity = request.headers.get("x-test-identity")
            if not identity:
                raise HTTPException(401, "Authentication required.")
            return identity
        def profile(identity):
            role, user = identity.split(":", 1)
            return {"role": role, "identifier": user, "year": None}
        self.patches = [
            patch.object(main, "SessionLocal", self.sessions), patch.object(main, "engine", self.engine),
            patch.object(main, "require_clerk_user_id", subject),
            patch.object(main, "resolve_profile_for_clerk_user_id", profile),
            patch.object(main, "rate_limit_retry_after", return_value=None),
        ]
        for replacement in self.patches:
            replacement.start()
        with self.sessions() as db:
            db.add_all([Mentor(id=1, username="Dr Rao"), Mentor(id=2, username="Dr Shah")])
            db.commit()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        for replacement in reversed(self.patches):
            replacement.stop()
        self.engine.dispose()

    def call(self, method, path, user="Dr Rao", role="mentor", **options):
        return self.client.request(method, path, headers={"x-test-identity": f"{role}:{user}"}, **options)

    def upload(self, rows, user="Dr Rao"):
        return self.call("POST", "/mentor/students/import", user=user,
                         files={"file": ("roster.xlsx", workbook_bytes(rows))})

    def roster(self, user="Dr Rao"):
        response = self.call("GET", "/mentor/students", user=user)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_import_filters_by_mentor_and_preserves_student_names(self):
        rows = [["Student Name", "PRN", "Mentor Name", "Group"],
                ["Asha", "S001", "Dr Rao", "A"], ["Vivek", "S002", "Dr Shah", "B"]]
        self.assertEqual(self.upload(rows).json()["added"], 1)
        self.assertEqual(self.roster("Dr Shah"), [])
        self.assertEqual(self.upload(rows, "Dr Shah").json()["added"], 1)
        self.assertEqual(self.upload(rows).json()["updated"], 1)
        self.assertEqual(self.roster()[0]["student_name"], "Asha")
        self.assertEqual(self.roster("Dr Shah")[0]["student_name"], "Vivek")

    def test_sheet_without_mentor_column_replaces_only_uploading_mentors_roster(self):
        self.assertEqual(self.upload([["Student Name", "PRN"], ["Old", "S001"], ["Keep", "S002"]]).status_code, 200)
        response = self.upload([["Student Name", "PRN"], ["Updated", "S002"]])
        self.assertEqual(response.json()["removed"], 1)
        self.assertEqual(self.roster()[0]["student_name"], "Updated")
        wrong = self.upload([["Student Name", "PRN", "Guide"], ["Other", "S003", "Dr Shah"]])
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(len(self.roster()), 1)

    def test_add_student_uses_verified_mentor_and_rejects_spoofing(self):
        payload = {"student_name": " New Student ", "prn": "M001", "group_number": "7"}
        self.assertEqual(self.call("POST", "/mentor/students", json={**payload, "mentor_user": "Dr Shah"}).status_code, 422)
        self.assertEqual(self.call("POST", "/mentor/students", json=payload).status_code, 201)
        self.assertEqual(self.roster()[0]["mentor_name"], "Dr Rao")
        self.assertEqual(self.roster("Dr Shah"), [])
        self.assertEqual(self.call("POST", "/mentor/students", json=payload).status_code, 409)
        self.assertEqual(self.call("POST", "/mentor/students", json={**payload, "student_name": " "}).status_code, 422)

    def test_manual_transfer_is_blocked_and_other_roster_details_are_private(self):
        payload = {"student_name": "Private name", "prn": "124A9023", "group_number": "12"}
        self.assertEqual(self.call("POST", "/mentor/students", user="Dr Shah", json=payload).status_code, 201)
        conflict = self.call("POST", "/mentor/students", json={**payload, "prn": "124a9023"})
        self.assertEqual(conflict.status_code, 409)
        self.assertIsInstance(conflict.json()["detail"], str)
        self.assertNotIn("Private name", conflict.text)
        self.assertEqual(self.call("POST", "/mentor/students", json={**payload, "transfer_existing": True}).status_code, 422)
        self.assertEqual(self.roster(), [])
        self.assertEqual(len(self.roster("Dr Shah")), 1)

    def test_dashboard_counts_canonical_projects_and_reviews_are_owner_scoped(self):
        for name, roll, group in [("Asha", "D001", "5"), ("Mira", "D002", "5"), ("Vivek", "D003", "16")]:
            response = self.call("POST", "/mentor/students", json={"student_name": name, "prn": roll, "group_number": group})
            self.assertEqual(response.status_code, 201)
        with self.sessions() as db:
            db.add_all([Team(id=1, team_name="5"), Team(id=2, team_name="16"),
                        Project(team_id=1, assigned_mentor_id=1), Project(team_id=2, assigned_mentor_id=1),
                        TeamMember(team_id=1, roll_no="D001"), TeamMember(team_id=1, roll_no="D002"),
                        TeamMember(team_id=2, roll_no="D003")])
            db.commit()
        dashboard = self.call("GET", "/mentor/dashboard").json()
        self.assertEqual((dashboard["assigned_students"], dashboard["active_projects"]), (3, 2))
        payload = {"group_number": "5", "review_type": "Progress Review-1", "review_date": "2099-01-01",
                   "review_time": "10:00", "notes": "Bring report"}
        self.assertEqual(self.call("POST", "/mentor/reviews", json={**payload, "group_number": "99"}).status_code, 400)
        review = self.call("POST", "/mentor/reviews", json=payload)
        self.assertEqual(review.status_code, 201)
        url = f"/mentor/reviews/{review.json()['id']}"
        self.assertEqual(self.call("PATCH", url, user="Dr Shah", json={"status": "completed"}).status_code, 404)
        self.assertEqual(self.call("PATCH", url, json={"status": "completed"}).status_code, 200)
        final = self.call("GET", "/mentor/dashboard").json()
        self.assertEqual((final["pending_reviews"], final["reviews_done"]), (0, 1))

    def test_axiom_uses_stored_context_and_history(self):
        with self.sessions() as db:
            db.add(Team(id=1, team_name="5"))
            db.add(Project(id=1, team_id=1, project_name="Attendance", project_abstract="Face recognition", assigned_mentor_id=1))
            db.commit()
        prompts = []
        async def chatbot(prompt):
            prompts.append(prompt)
            yield "Analysis ready"
        with patch.object(main, "Chatbot_stream", chatbot):
            response = self.call("POST", "/mentor/axiom-stream", json={"project_id": 1, "question": "Improve?",
                                  "history": [{"role": "user", "content": "Scope?"}]})
        self.assertEqual(response.text, "Analysis ready")
        self.assertIn("Face recognition", prompts[0])
        self.assertIn("Scope?", prompts[0])

    def test_invitation_accept_is_scoped_to_verified_invitee(self):
        with self.sessions() as db:
            db.add_all([Student(roll_no=f"S{i}") for i in range(1, 4)])
            db.commit()
        self.assertEqual(self.call("POST", "/create-team", role="student", user="S1", json={"team_name": "JOD"}).status_code, 200)
        invite = self.call("POST", "/team-invitations", role="student", user="S1", json={"invitee_roll_no": "s2"})
        self.assertEqual(invite.status_code, 201)
        self.assertEqual(self.call("POST", "/team-invitations", role="student", user="S1", json={"invitee_roll_no": "S2"}).status_code, 409)
        url = f"/team-invitations/{invite.json()['id']}"
        self.assertEqual(self.call("PATCH", url, role="student", user="S3", json={"action": "accept"}).status_code, 404)
        response = self.call("PATCH", url, role="student", user="S2", json={"action": "accept"})
        self.assertEqual(response.json()["members"], ["S1", "S2"])
        self.assertEqual(self.call("GET", "/team-invitations", role="student", user="S2").json(), [])
        self.assertEqual(self.call("POST", "/join-team", role="student", user="S2", json={"team_code": "INVALID"}).status_code, 400)

    def test_team_submission_assignment_and_resubmission_preserve_ownership(self):
        with self.sessions() as db:
            db.add_all([Student(roll_no="S1"), Student(roll_no="S2")])
            db.commit()
        created = self.call("POST", "/create-team", role="student", user="S1", json={"team_name": "Pair"})
        self.assertEqual(created.status_code, 200)
        idea = {"project_name": "Original idea", "project_abstract": "Our approach"}
        self.assertEqual(self.call("POST", "/submit-project", role="student", user="S1", json=idea).status_code, 400)
        joined = self.call("POST", "/join-team", role="student", user="S2", json={"team_code": created.json()["team_code"]})
        self.assertEqual(joined.status_code, 200)
        submitted = self.call("POST", "/submit-project", role="student", user="S1", json=idea)
        self.assertEqual(submitted.status_code, 200)
        project_id = submitted.json()["project_id"]
        url = f"/api/projects/{project_id}/assign"
        self.assertEqual(self.call("PATCH", url).status_code, 200)
        self.assertEqual(self.call("PATCH", url, user="Dr Shah").status_code, 409)
        self.assertEqual(self.call("GET", "/api/projects", user="Dr Shah").json(), [])
        updated = self.call("POST", "/submit-project", role="student", user="S2", json={**idea, "project_name": "Refined idea"})
        self.assertEqual(updated.json()["project_id"], project_id)
        imported = self.upload([["Student Name", "PRN", "Project"], ["One", "S1", "Stale title"], ["Two", "S2", "Stale title"]])
        self.assertEqual(imported.status_code, 200)
        self.assertTrue(all(row["project_name"] == "Refined idea" for row in self.roster()))
        with self.sessions() as db:
            self.assertEqual(db.get(Project, project_id).assigned_mentor_id, 1)
        self.assertEqual(self.call("POST", "/leave-team", role="student", user="S2").status_code, 200)
        self.assertEqual(self.call("POST", "/submit-project", role="student", user="S1", json=idea).status_code, 400)

    def test_group_sheet_carries_guide_and_extra_members(self):
        rows = [["College"], ["Group no", "Rollno", "Name of the Student", "Finalized idea", "Guide"],
                [5, "S010", "Ovee", "New idea", "Prof. Dr Rao"],
                [None, "S011", "Naman", None, None, None, "S00013", "Krishna K"],
                [6, "S012", "Other", "Other idea", "Dr Shah"]]
        self.assertEqual(self.upload(rows).status_code, 200)
        self.assertEqual([row["student_name"] for row in self.roster()], ["Krishna K", "Naman", "Ovee"])
        self.assertTrue(all(row["project_name"] == "New idea" for row in self.roster()))

    def test_edit_delete_and_import_cannot_take_other_mentors_roster(self):
        payload = {"student_name": "Asha", "prn": "S001", "group_number": "5"}
        rao = self.call("POST", "/mentor/students", json=payload).json()["id"]
        shah = self.call("POST", "/mentor/students", user="Dr Shah", json={**payload, "prn": "S002"}).json()["id"]
        self.assertEqual(self.call("PUT", f"/mentor/students/{shah}", json=payload).status_code, 404)
        self.assertEqual(self.call("DELETE", f"/mentor/students/{shah}").status_code, 404)
        self.assertEqual(self.upload([["Student Name", "PRN"], ["Claimed", "S002"]]).status_code, 409)
        self.assertEqual(self.call("PUT", f"/mentor/students/{rao}", json={**payload, "student_name": "Updated"}).status_code, 200)
        self.assertEqual(self.call("DELETE", f"/mentor/students/{rao}").status_code, 200)
        self.assertEqual(self.roster(), [])
        self.assertEqual(len(self.roster("Dr Shah")), 1)

if __name__ == "__main__":
    unittest.main()
