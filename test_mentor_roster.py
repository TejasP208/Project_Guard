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
