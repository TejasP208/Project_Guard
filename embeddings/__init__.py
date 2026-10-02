"""Server-side text embeddings for Project Guard."""

from .cloudflare import CloudflareEmbeddingClient, EmbeddingError

__all__ = ["CloudflareEmbeddingClient", "EmbeddingError"]
