# Cloudflare Qwen embeddings

This module generates one vector for one text input. It does not change the
current plagiarism checker or its SBERT index.

## Configuration

For local development, put `CLOUDFLARE_ACCOUNT_ID` and
`CLOUDFLARE_API_TOKEN` in the project root `.env` file. The adapter loads
that file automatically. In deployment, set both values in the backend
environment settings. The token needs Workers AI access. Keep it out of
browser code and Git. `httpx` and `python-dotenv` are already in the
project's `requirements.txt`.

## Interface

```python
from embeddings import CloudflareEmbeddingClient

vector = CloudflareEmbeddingClient().embed(
    "Project title. Project abstract or other extracted text."
)
```

`embed(text)` accepts a nonempty string and returns a list of 1024 finite
floats. It raises `ValueError` for empty input or missing configuration and
`EmbeddingError` for a failed request or invalid response. It does not
normalize the returned values; the future similarity query should compute
cosine similarity. The model is `@cf/qwen/qwen3-embedding-0.6b`, and the
request sends `{"text": [text]}` to Cloudflare Workers AI.

Use the same text construction for indexed projects and incoming submissions.
The current index uses `"{project_name}. {project_abstract}"`; changing this
format requires re-embedding indexed projects. Long documents will need a
separate chunking strategy before this adapter is used in production.

To try it manually after adding the two values to `.env`:

```powershell
python -c "from embeddings import CloudflareEmbeddingClient; print(len(CloudflareEmbeddingClient().embed('Sample project abstract')))"
```

To compare a related project description with an unrelated one:

```powershell
python -m embeddings.compare_examples
```

This makes three Workers AI requests and prints two cosine scores. The
related description should rank higher. These examples only check ranking;
they do not define a plagiarism threshold or percentage.

On 2026-09-29, the sample comparison returned 0.8246 for the related pair
and 0.4234 for the unrelated pair. These scores describe only the three
sample texts above; use representative project submissions before choosing
any score threshold.

Cloudflare model and REST API documentation:

- https://developers.cloudflare.com/workers-ai/models/qwen3-embedding-0.6b/
- https://developers.cloudflare.com/workers-ai/get-started/rest-api/
