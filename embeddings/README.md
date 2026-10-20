# Cloudflare Qwen embeddings

This module provides the server-side Qwen embedding client used by the
PostgreSQL-backed project submission, indexing, search, and plagiarism-check
paths. PostgreSQL stores project vectors in the `projects.embedding` pgvector
column. The legacy SBERT `.npy` index and scripts remain separate local tools.

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
`EmbeddingError` for a failed request or invalid response. The model is
`@cf/qwen/qwen3-embedding-0.6b`, and the request sends `{"text": [text]}` to
Cloudflare Workers AI. Project search and plagiarism checks compare stored
vectors with cosine distance through pgvector.

The project index uses `"{project_name}. {project_abstract}"`; changing this
format requires re-embedding indexed projects. The indexer fills missing
project vectors; the configured PostgreSQL database currently has vectors for
all 72 project records (checked 2026-10-06). For plagiarism checks, the
title/description and document text are embedded separately, and the strongest
chunk match is used for each stored project. Documents support chunks of up to
3000 characters with a 200-character overlap, preferring sentence boundaries
and then word boundaries. The checker uses the full extracted document up to
the accepted 10,000-character limit. `embed_many(texts)` batches up to eight texts per
Cloudflare request and returns one vector for each input in order.

The combined TF-IDF/Qwen score (60%/40%) is provisional. Project submission
currently requires an abstract, document, and prior similarity check of the
same content. The submission limit is 30%; scores above 30% are
blocked. The percentage estimates similarity to stored projects and is not
proof of plagiarism. To evaluate the cutoff, collect representative labeled cases and run
`python -m embeddings.calibrate path/to/labeled_cases.csv`; it requires at
least 10 similar and 10 unrelated examples and evaluates the current configured
weights and candidate cutoffs. Treat that result as exploratory, review errors
on separate held-out cases, and document the chosen weights and cutoff before
changing the 30% submission policy. The script does not optimize weights, so the weights and cutoff
still need separate evidence and review.

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
