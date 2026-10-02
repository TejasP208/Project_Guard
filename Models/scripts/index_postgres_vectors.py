"""Embed PostgreSQL projects into the pgvector column."""

from embeddings.project_vectors import index_projects


if __name__ == "__main__":
    count = index_projects()
    print(f"Indexed {count} project(s) into PostgreSQL pgvector.")
