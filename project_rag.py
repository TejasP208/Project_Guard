"""Team-scoped indexing and retrieval for uploaded project documents."""

import logging
import re

from sqlalchemy import func

from models import ProjectDocument, ProjectDocumentChunk


logger = logging.getLogger(__name__)
CHUNK_SIZE = 2400
CHUNK_OVERLAP = 240
MAX_CONTEXT_CHUNKS = 6


def split_document(text: str) -> list[str]:
    """Split long text on nearby paragraph or sentence boundaries."""
    text = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n")).strip()
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n\n", start + CHUNK_SIZE // 2, end),
                           text.rfind(". ", start + CHUNK_SIZE // 2, end))
            if boundary > start:
                end = boundary + (2 if text[boundary:boundary + 2] in {"\n\n", ". "} else 1)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - CHUNK_OVERLAP)
    return chunks


def index_document(document_id: int, uploaded_at: str, session_factory, embedder_factory) -> bool:
    """Index one document; stale upload jobs cannot reactivate replaced content."""
    with session_factory() as db:
        document = db.get(ProjectDocument, document_id)
        if not document or not document.active or document.uploaded_at != uploaded_at:
            return False
        text = document.extracted_text
    try:
        chunks = split_document(text)
        vectors = embedder_factory().embed_many(chunks)
        if len(chunks) != len(vectors):
            raise ValueError("Embedding count does not match chunk count")
        with session_factory() as db:
            document = db.get(ProjectDocument, document_id)
            if not document or not document.active or document.uploaded_at != uploaded_at:
                return False
            db.query(ProjectDocumentChunk).filter_by(document_id=document_id).delete()
            for number, (chunk, vector) in enumerate(zip(chunks, vectors), start=1):
                db.add(ProjectDocumentChunk(document_id=document.id, team_id=document.team_id,
                                            slot=document.slot, chunk_number=number, text=chunk,
                                            embedding=vector))
            document.index_status = "ready"
            document.index_error = None
            db.commit()
        return True
    except Exception as error:
        logger.warning("Project document indexing failed for %s (%s)", document_id, type(error).__name__)
        with session_factory() as db:
            document = db.get(ProjectDocument, document_id)
            if document and document.active and document.uploaded_at == uploaded_at:
                document.index_status = "failed"
                document.index_error = str(error)[:300]
                db.commit()
        return False


def index_missing_for_team(team_id: int, session_factory, embedder_factory) -> None:
    """Backfill older uploads or retry a failed index when a team first opens chat."""
    with session_factory() as db:
        pending = [(row.id, row.uploaded_at) for row in db.query(ProjectDocument).filter(
            ProjectDocument.team_id == team_id, ProjectDocument.active.is_(True),
            ProjectDocument.index_status != "ready").all()]
    for document_id, uploaded_at in pending:
        index_document(document_id, uploaded_at, session_factory, embedder_factory)


def retrieve_team_passages(team_id: int, question: str, session_factory, embedder_factory,
                           limit: int = MAX_CONTEXT_CHUNKS) -> list[dict]:
    """Fuse semantic and exact-term matches, always filtering by active team documents."""
    with session_factory() as db:
        base = db.query(ProjectDocumentChunk, ProjectDocument).join(
            ProjectDocument, ProjectDocument.id == ProjectDocumentChunk.document_id).filter(
                ProjectDocumentChunk.team_id == team_id,
                ProjectDocument.team_id == team_id,
                ProjectDocument.active.is_(True),
                ProjectDocument.index_status == "ready")
        if not db.query(base.exists()).scalar():
            return []
        vector = embedder_factory().embed(question)
        distance = ProjectDocumentChunk.embedding.cosine_distance(vector)
        semantic = base.order_by(distance).limit(12).all()
        search = func.plainto_tsquery("english", question)
        rank = func.ts_rank_cd(func.to_tsvector("english", ProjectDocumentChunk.text), search)
        lexical = base.filter(func.to_tsvector("english", ProjectDocumentChunk.text).op("@@")(search)).order_by(
            rank.desc()).limit(12).all()
        scores = {}
        rows = {}
        for candidates in (semantic, lexical):
            for position, (chunk, document) in enumerate(candidates, start=1):
                scores[chunk.id] = scores.get(chunk.id, 0) + 1 / (60 + position)
                rows[chunk.id] = (chunk, document)
        chosen = sorted(scores, key=lambda key: scores[key], reverse=True)[:limit]
        return [{"document_id": rows[key][1].id, "slot": rows[key][1].slot,
                 "filename": rows[key][1].filename, "chunk_number": rows[key][0].chunk_number,
                 "text": rows[key][0].text} for key in chosen]
