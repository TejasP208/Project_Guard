"""Cloudflare Workers AI adapter for Qwen3 text embeddings."""

import math
import os

import httpx
from dotenv import load_dotenv


MODEL = "@cf/qwen/qwen3-embedding-0.6b"
DIMENSIONS = 1024

# Load local development credentials from the project root .env file.
load_dotenv()


class EmbeddingError(RuntimeError):
    """The embedding service failed or returned an unusable vector."""


class CloudflareEmbeddingClient:
    def __init__(self, account_id=None, api_token=None, timeout=30.0):
        self.account_id = account_id or os.getenv("CLOUDFLARE_ACCOUNT_ID")
        self.api_token = api_token or os.getenv("CLOUDFLARE_API_TOKEN")
        if not self.account_id or not self.api_token:
            raise ValueError("Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN")
        self.timeout = timeout

    def embed(self, text: str) -> list[float]:
        """Return one 1024-dimensional vector for nonempty text."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Embedding text must be a nonempty string")

        url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{self.account_id}/ai/run/{MODEL}"
        )
        try:
            response = httpx.post(
                url,
                headers={"Authorization": f"Bearer {self.api_token}"},
                json={"text": [text.strip()]},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingError("Cloudflare embedding request failed") from exc

        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise EmbeddingError("Cloudflare embedding request was unsuccessful")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise EmbeddingError("Cloudflare embedding response has no result")
        data = result.get("data")
        if not isinstance(data, list) or len(data) != 1:
            raise EmbeddingError("Cloudflare embedding response must contain one vector")
        vector = data[0]
        if (
            not isinstance(vector, list)
            or len(vector) != DIMENSIONS
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in vector
            )
        ):
            raise EmbeddingError("Cloudflare returned an invalid embedding vector")
        return [float(value) for value in vector]
