"""Index replacement and stale upload behavior for team document search."""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, ProjectDocument, ProjectDocumentChunk, Team
from project_rag import index_document, split_document


class FakeEmbeddings:
    def embed_many(self, texts):
        return [[0.1] * 1024 for _ in texts]


class ProjectRagTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            db.add(Team(id=1, team_name="One"))
            db.add(ProjectDocument(id=1, team_id=1, slot="project_idea", filename="idea.txt",
                                   content_type="text/plain", content=b"first idea", extracted_text="first idea",
                                   uploaded_by="S1", uploaded_at="first"))
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_replacement_removes_old_passages_and_stale_job_cannot_restore_them(self):
        self.assertTrue(index_document(1, "first", self.sessions, FakeEmbeddings))
        with self.sessions() as db:
            document = db.get(ProjectDocument, 1)
            document.extracted_text = "second idea"
            document.uploaded_at = "second"
            document.index_status = "pending"
            db.query(ProjectDocumentChunk).filter_by(document_id=1).delete()
            db.commit()
        self.assertFalse(index_document(1, "first", self.sessions, FakeEmbeddings))
        self.assertTrue(index_document(1, "second", self.sessions, FakeEmbeddings))
        with self.sessions() as db:
            self.assertEqual([row.text for row in db.query(ProjectDocumentChunk).all()], ["second idea"])
            self.assertEqual(db.get(ProjectDocument, 1).index_status, "ready")

    def test_long_text_is_chunked_with_overlap(self):
        text = "A paragraph. " * 500
        chunks = split_document(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 2400 for chunk in chunks))
        self.assertIn("A paragraph", chunks[0])


if __name__ == "__main__":
    unittest.main()
