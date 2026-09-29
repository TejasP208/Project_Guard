"""Persist and search 1024-dimensional project embeddings in PostgreSQL."""

from __future__ import annotations

from sqlalchemy import select

from database import SessionLocal, engine
from embeddings import CloudflareEmbeddingClient
from models import Project


def _require_postgresql() -> None:
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Project vector storage requires PostgreSQL with pgvector enabled.")


def index_projects() -> int:
    """Embed projects that do not yet have a vector; return the indexed count."""
    _require_postgresql()
    client = CloudflareEmbeddingClient()
    with SessionLocal() as db:
        projects = db.scalars(
            select(Project).where(Project.embedding.is_(None)).order_by(Project.id)
        ).all()
        for project in projects:
            text = f"{project.project_name or ''}. {project.project_abstract or ''}".strip()
            project.embedding = client.embed(text)
        db.commit()
        return len(projects)


def find_similar_projects(title: str, abstract: str = "", top_k: int = 5) -> list[dict]:
    """Return nearest stored projects ordered by cosine similarity."""
    _require_postgresql()
    if top_k < 1:
        raise ValueError("top_k must be at least 1")

    client = CloudflareEmbeddingClient()
    query = client.embed(f"{title}. {abstract}".strip())
    distance = Project.embedding.cosine_distance(query)
    statement = (
        select(Project, distance.label("cosine_distance"))
        .where(Project.embedding.is_not(None))
        .order_by(distance)
        .limit(top_k)
    )
    with SessionLocal() as db:
        rows = db.execute(statement).all()
        return [
            {
                "project_id": project.id,
                "project_name": project.project_name,
                "project_abstract": project.project_abstract,
                "similarity": 1.0 - float(cosine_distance),
            }
            for project, cosine_distance in rows
        ]
