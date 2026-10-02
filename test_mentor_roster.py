from io import BytesIO
import unittest

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from models import Base, Mentor, Student


def workbook_bytes(rows):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


class MentorRosterTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.original_session_factory = main.SessionLocal
        main.SessionLocal = self.session_factory
        with self.session_factory() as session:
            session.add_all([Mentor(username="Dr Rao", password="x"), Mentor(username="Dr Shah", password="x")])
            session.commit()
        self.client = TestClient(main.app)

    def tearDown(self):
        main.SessionLocal = self.original_session_factory
        self.client.close()
        self.engine.dispose()

    def test_import_filters_by_mentor_and_preserves_student_names(self):
        data = workbook_bytes([
            ["Student Name", "PRN", "Mentor Name", "Group"],
            ["Asha Patil", "S001", "Dr Rao", "Group A"],
            ["Vivek Das", "S002", "Dr Shah", "Group B"],
        ])
        response = self.client.post(
            "/mentor/students/import",
            data={"mentor_user": "Dr Rao"},
            files={"file": ("roster.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["added"], 2)

        rao = self.client.get("/mentor/students", params={"mentor_user": "Dr Rao"}).json()
        shah = self.client.get("/mentor/students", params={"mentor_user": "Dr Shah"}).json()
        self.assertEqual([(s["student_name"], s["prn"]) for s in rao], [("Asha Patil", "S001")])
        self.assertEqual([s["student_name"] for s in shah], ["Vivek Das"])
        lowercase = self.client.get("/mentor/students", params={"mentor_user": "dr rao"}).json()
        self.assertEqual([s["student_name"] for s in lowercase], ["Asha Patil"])

        repeat = self.client.post(
            "/mentor/students/import",
            data={"mentor_user": "Dr Rao"},
            files={"file": ("roster.xlsx", data)},
        )
        self.assertEqual(repeat.json()["updated"], 2)
        self.assertEqual(len(self.client.get("/mentor/students", params={"mentor_user": "Dr Rao"}).json()), 1)

    def test_sheet_without_mentor_column_assigns_uploading_mentor(self):
        data = workbook_bytes([["Name of Student", "Roll No"], ["Mira Joshi", "S003"]])
        response = self.client.post(
            "/mentor/students/import",
            data={"mentor_user": "Dr Rao"},
            files={"file": ("students.xlsx", data)},
        )
        self.assertEqual(response.status_code, 200)
        students = self.client.get("/mentor/students", params={"mentor_user": "Dr Rao"}).json()
        self.assertEqual(students[0]["student_name"], "Mira Joshi")

    def test_add_student_manually_assigns_signed_in_mentor(self):
        payload = {
            "mentor_user": "dr rao", "student_name": "  New Student  ",
            "prn": "M001", "group_number": "7", "project_name": "Manual Project", "year": "3rd Year",
        }
        created = self.client.post("/mentor/students", json=payload)
        self.assertEqual(created.status_code, 201)
        roster = self.client.get("/mentor/students", params={"mentor_user": "Dr Rao"}).json()
        self.assertEqual(len(roster), 1)
        self.assertEqual((roster[0]["student_name"], roster[0]["mentor_name"], roster[0]["group_number"]),
                         ("New Student", "Dr Rao", "7"))
        self.assertEqual(self.client.get("/mentor/students", params={"mentor_user": "Dr Shah"}).json(), [])
        self.assertEqual(self.client.post("/mentor/students", json=payload).status_code, 409)
        self.assertEqual(self.client.post("/mentor/students", json={**payload, "student_name": " ", "prn": "M002"}).status_code, 400)

    def test_manual_add_can_confirm_move_of_existing_prn(self):
        original = {
            "mentor_user": "Dr Shah", "student_name": "Krishna Kshirsagar",
            "prn": "124A9023", "group_number": "12", "project_name": "Existing Project", "year": "3",
        }
        created = self.client.post("/mentor/students", json=original)
        self.assertEqual(created.status_code, 201)
        payload = {
            "mentor_user": "Dr Rao", "student_name": "Krishna",
            "prn": "124a9023", "group_number": "16", "project_name": "", "year": "",
        }
        conflict = self.client.post("/mentor/students", json=payload)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"]["mentor_name"], "Dr Shah")
        self.assertEqual(conflict.json()["detail"]["group_number"], "12")
        self.assertEqual(self.client.get("/mentor/students", params={"mentor_user": "Dr Rao"}).json(), [])

        moved = self.client.post("/mentor/students", json={**payload, "transfer_existing": True})
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["id"], created.json()["id"])
        self.assertEqual(self.client.get("/mentor/students", params={"mentor_user": "Dr Shah"}).json(), [])
        roster = self.client.get("/mentor/students", params={"mentor_user": "Dr Rao"}).json()
        self.assertEqual(len(roster), 1)
        self.assertEqual((roster[0]["student_name"], roster[0]["group_number"], roster[0]["project_name"]),
                         ("Krishna", "16", "Existing Project"))

    def test_dashboard_uses_mentor_data_and_persists_review_status(self):
        for student_name, prn, group, project in [
            ("Asha", "D001", "5", "Project One"),
            ("Mira", "D002", "5", "Project One"),
            ("Vivek", "D003", "16", "Project Two"),
        ]:
            response = self.client.post("/mentor/students", json={
                "mentor_user": "Dr Rao", "student_name": student_name, "prn": prn,
                "group_number": group, "project_name": project,
            })
            self.assertEqual(response.status_code, 201)

        dashboard = self.client.get("/mentor/dashboard", params={"mentor_user": "Dr Rao"})
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.json()["assigned_students"], 3)
        self.assertEqual(dashboard.json()["active_projects"], 2)

        invalid_group = self.client.post("/mentor/reviews", json={
            "mentor_user": "Dr Rao", "group_number": "99", "review_type": "Progress Review-1",
            "review_date": "2099-01-01", "review_time": "10:00", "notes": "",
        })
        self.assertEqual(invalid_group.status_code, 400)
        review = self.client.post("/mentor/reviews", json={
            "mentor_user": "Dr Rao", "group_number": "5", "review_type": "Progress Review-1",
            "review_date": "2099-01-01", "review_time": "10:00", "notes": "Bring the report",
        })
        self.assertEqual(review.status_code, 201)
        self.assertEqual(self.client.get("/mentor/dashboard", params={"mentor_user": "Dr Rao"}).json()["pending_reviews"], 1)

        completed = self.client.patch(f"/mentor/reviews/{review.json()['id']}", json={
            "mentor_user": "Dr Rao", "status": "completed",
        })
        self.assertEqual(completed.status_code, 200)
        final = self.client.get("/mentor/dashboard", params={"mentor_user": "Dr Rao"}).json()
        self.assertEqual((final["pending_reviews"], final["reviews_done"]), (0, 1))

    def test_mentor_axiom_uses_project_context_and_streams_chatbot_response(self):
        captured = []
        original_chatbot = main.Chatbot_stream

        async def fake_chatbot(prompt):
            captured.append(prompt)
            yield "Project "
            yield "analysis ready."

        main.Chatbot_stream = fake_chatbot
        try:
            response = self.client.post("/mentor/axiom-stream", json={
                "question": "What should I improve?",
                "project_title": "Smart Attendance",
                "project_abstract": "Uses face recognition for attendance.",
                "group_name": "5",
                "year": "3rd Year",
                "history": [{"role": "user", "content": "Check the scope"}],
            })
        finally:
            main.Chatbot_stream = original_chatbot
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "Project analysis ready.")
        self.assertIn("Project title: Smart Attendance", captured[0])
        self.assertIn("Project abstract: Uses face recognition", captured[0])
        self.assertIn("Mentor question: What should I improve?", captured[0])

    def test_team_invitation_can_be_sent_and_accepted(self):
        with self.session_factory() as session:
            session.add_all([
                Student(roll_no="124A9001", password="x", year="3rd Year"),
                Student(roll_no="124A9002", password="x", year="3rd Year"),
                Student(roll_no="124A9003", password="x", year="3rd Year"),
            ])
            session.commit()
        team = self.client.post("/create-team", json={
            "team_name": "JOD", "max_members": 4, "roll_no": "124A9001",
        })
        self.assertEqual(team.status_code, 200)
        missing = self.client.post("/team-invitations", json={
            "inviter_roll_no": "124A9001", "invitee_roll_no": "DOES-NOT-EXIST",
        })
        self.assertEqual(missing.status_code, 404)
        invitation = self.client.post("/team-invitations", json={
            "inviter_roll_no": "124A9001", "invitee_roll_no": "124a9002",
        })
        self.assertEqual(invitation.status_code, 201)
        duplicate = self.client.post("/team-invitations", json={
            "inviter_roll_no": "124A9001", "invitee_roll_no": "124A9002",
        })
        self.assertEqual(duplicate.status_code, 409)
        incoming = self.client.get("/team-invitations", params={"roll_no": "124A9002"}).json()
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0]["team_name"], "JOD")
        wrong_student = self.client.patch(f"/team-invitations/{invitation.json()['id']}", json={
            "roll_no": "124A9003", "action": "accept",
        })
        self.assertEqual(wrong_student.status_code, 404)
        accepted = self.client.patch(f"/team-invitations/{invitation.json()['id']}", json={
            "roll_no": "124A9002", "action": "accept",
        })
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["members"], ["124A9001", "124A9002"])
        self.assertEqual(self.client.get("/team-invitations", params={"roll_no": "124A9002"}).json(), [])

    def test_group_sheet_carries_guide_and_matches_name_without_title(self):
        data = workbook_bytes([
            ["College"],
            ["Group no", "Rollno", "Name of the Student", "Finalized idea", "Guide"],
            [5, "S010", "Ovee Wakchaure", "New idea", "Prof. Dr Rao"],
            [None, "S011", "Naman Gandhi", None, None, None, "S00013", "Krishna K"],
            [6, "S012", "Other Student", "Other idea", "Dr Shah"],
        ])
        response = self.client.post(
            "/mentor/students/import",
            data={"mentor_user": "Dr Rao"},
            files={"file": ("guides.xlsx", data)},
        )
        self.assertEqual(response.status_code, 200)
        students = self.client.get("/mentor/students", params={"mentor_user": "Dr Rao"}).json()
        self.assertEqual([s["student_name"] for s in students], ["Krishna K", "Naman Gandhi", "Ovee Wakchaure"])
        self.assertEqual([s["team_name"] for s in students], ["5", "5", "5"])
        self.assertEqual([s["group_number"] for s in students], ["5", "5", "5"])
        self.assertEqual([s["project_name"] for s in students], ["New idea", "New idea", "New idea"])

    def test_edit_and_delete_affect_only_the_mentors_roster(self):
        data = workbook_bytes([
            ["Student Name", "PRN", "Mentor Name", "Group"],
            ["Asha Patil", "S001", "Dr Rao", 5],
            ["Vivek Das", "S002", "Dr Shah", 6],
        ])
        with self.session_factory() as session:
            session.add(Student(roll_no="S001", password="saved-login", year="3rd Year"))
            session.commit()
        imported = self.client.post(
            "/mentor/students/import", data={"mentor_user": "Dr Rao"}, files={"file": ("roster.xlsx", data)}
        )
        self.assertEqual(imported.status_code, 200)
        rao = self.client.get("/mentor/students", params={"mentor_user": "Dr Rao"}).json()[0]
        shah = self.client.get("/mentor/students", params={"mentor_user": "Dr Shah"}).json()[0]

        payload = {
            "mentor_user": "Dr Rao", "student_name": "Asha P", "prn": "S001",
            "group_number": "16", "project_name": "Updated Project", "year": "3rd Year",
        }
        self.assertEqual(self.client.put(f"/mentor/students/{shah['id']}", json=payload).status_code, 404)
        self.assertEqual(self.client.delete(f"/mentor/students/{shah['id']}", params={"mentor_user": "Dr Rao"}).status_code, 404)
        self.assertEqual(self.client.put(f"/mentor/students/{rao['id']}", json=payload).status_code, 200)
        updated = self.client.get("/mentor/students", params={"mentor_user": "Dr Rao"}).json()[0]
        self.assertEqual((updated["student_name"], updated["group_number"], updated["project_name"]),
                         ("Asha P", "16", "Updated Project"))

        self.assertEqual(self.client.delete(f"/mentor/students/{rao['id']}", params={"mentor_user": "Dr Rao"}).status_code, 200)
        self.assertEqual(self.client.get("/mentor/students", params={"mentor_user": "Dr Rao"}).json(), [])
        self.assertEqual(len(self.client.get("/mentor/students", params={"mentor_user": "Dr Shah"}).json()), 1)
        with self.session_factory() as session:
            self.assertIsNotNone(session.query(Student).filter(Student.roll_no == "S001").first())


if __name__ == "__main__":
    unittest.main()
