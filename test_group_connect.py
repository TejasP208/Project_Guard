import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from group_connect import create_router
from mentor_roster import mentor_key
from models import Base, GroupMessage, Mentor, MentorReview, MentorStudent, Student


class GroupConnectTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        app = FastAPI()
        app.include_router(create_router(self.sessions))
        self.client = TestClient(app)
        with self.sessions() as db:
            db.add_all([Mentor(username="Dr Rao"), Mentor(username="Dr Shah")])
            db.add_all([Student(roll_no=roll) for roll in ["S001", "S002", "S003", "S004"]])
            db.add_all([
                MentorStudent(mentor_name="Dr Rao", mentor_key=mentor_key("Dr Rao"), student_name="Asha", prn="S001", group_name="5", project_name="Attendance"),
                MentorStudent(mentor_name="Dr Rao", mentor_key=mentor_key("Dr Rao"), student_name="Mira", prn="S002", group_name="5"),
                MentorStudent(mentor_name="Dr Shah", mentor_key=mentor_key("Dr Shah"), student_name="Vivek", prn="S003", group_name="5", project_name="Robotics"),
                MentorReview(mentor_name="Dr Rao", mentor_key=mentor_key("Dr Rao"), group_name="5", review_type="Progress Review-1", review_date="2099-01-01", review_time="10:00", status="scheduled", created_at="2026-10-02"),
            ])
            db.commit()
        self.room = self.groups("student", "S001")[0]["id"]

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def groups(self, role, user):
        response = self.client.get("/group-connect/groups", params={"role": role, "user": user})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def send(self, role, user, **values):
        return self.client.post("/group-connect/messages", json={"role": role, "user": user, "group_id": self.room, **values})

    def messages(self, role, user):
        return self.client.get("/group-connect/messages", params={"role": role, "user": user, "group_id": self.room})

    def test_student_sees_only_assigned_group_members_and_reviews(self):
        groups = self.groups("student", " s001 ")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["members"], ["Asha", "Mira"])
        self.assertEqual(groups[0]["mentor"], "Dr Rao")
        self.assertEqual(groups[0]["reviews"][0]["type"], "Progress Review-1")
        self.assertEqual(groups[0]["id"], self.groups("mentor", "dr rao")[0]["id"])
        self.assertNotEqual(groups[0]["id"], self.groups("student", "S003")[0]["id"])

    def test_messages_are_shared_by_mentor_and_group_members_and_persisted(self):
        self.assertEqual(self.send("mentor", "Dr Rao", text="Hello group").status_code, 201)
        self.assertEqual(self.send("student", "S001", text="  Hello mentor  ").status_code, 201)
        messages = self.messages("student", "S002").json()
        self.assertEqual([message["text"] for message in messages], ["Hello group", "Hello mentor"])
        self.assertEqual(messages[1]["name"], "Asha")
        self.assertEqual(self.messages("mentor", "Dr Rao").json(), messages)
        with self.sessions() as db:
            self.assertEqual(db.query(GroupMessage).count(), 2)

    def test_other_groups_and_mentors_cannot_read_or_write_the_room(self):
        for role, user in [("student", "S003"), ("student", "S004"), ("mentor", "Dr Shah")]:
            self.assertEqual(self.messages(role, user).status_code, 403)
            self.assertEqual(self.send(role, user, text="Wrong group").status_code, 403)
        self.assertEqual(self.groups("student", "S004"), [])
        self.assertEqual(self.client.get("/group-connect/groups", params={"role": "student", "user": "missing"}).status_code, 404)

    def test_meeting_links_are_shared_and_invalid_links_and_messages_rejected(self):
        url = "https://meet.google.com/abc-defg-hij"
        self.assertEqual(self.send("student", "S001", meet_link=url).status_code, 201)
        self.assertEqual(self.messages("mentor", "Dr Rao").json()[0]["meet_link"], url)
        for link in ["javascript:alert(1)", "https://meet.google.com.evil.test/abc-defg-hij", "https://meet.google.com/new"]:
            self.assertEqual(self.send("student", "S001", meet_link=link).status_code, 400)
        self.assertEqual(self.send("student", "S001", text=" ").status_code, 400)
        self.assertEqual(self.send("student", "S001", text="x" * 4001).status_code, 422)

    def test_reassigned_student_loses_access_to_previous_room(self):
        self.send("mentor", "Dr Rao", text="Private to group 5")
        with self.sessions() as db:
            student = db.query(MentorStudent).filter(MentorStudent.prn == "S001").one()
            student.group_name = "6"
            db.commit()
        self.assertEqual(self.messages("student", "S001").status_code, 403)
        self.assertEqual(self.send("student", "S001", text="Old room").status_code, 403)
        self.assertNotEqual(self.groups("student", "S001")[0]["id"], self.room)


if __name__ == "__main__":
    unittest.main()
