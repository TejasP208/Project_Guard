# Changes to Complete Before Deployment

This document tracks the project changes to complete before making Project Guard publicly available. These are planned changes, not instructions to deploy immediately.

## Frontend hosting

**Current state:** Static files are in `Frontend/` and route API requests through `Frontend/deployment-config.js`. It uses localhost for local development and requires an explicit HTTPS API origin on deployed domains.

**Planned changes:**
- [ ] Deploy `Frontend/` to Cloudflare Pages.
- [x] Route frontend API requests through one configurable API base URL.
- [ ] Set `Frontend/deployment-config.js` to the deployed Render API origin before publishing.
- [ ] Configure backend CORS to allow the deployed Cloudflare Pages domain.

## Backend hosting

**Current state:** FastAPI is started locally for development. Production startup now requires live Clerk keys and exact HTTPS CORS/authorized-party origins.

**Planned changes:**
- [ ] Deploy the API as a Render Web Service.
- [ ] Bind the server to `0.0.0.0` and Render's `$PORT`.
- [ ] Store Groq and Cloudflare credentials in Render environment settings; do not put them in frontend code.
- [ ] Account for the possibility that Render's free web services sleep while idle.

## Dependencies

**Current state:** `requirements.txt` may not clearly declare every imported runtime dependency.

**Planned changes:**
- [ ] Make the dependency list self-contained, including FastAPI, Uvicorn, SQLAlchemy, Passlib, `python-multipart`, the Groq SDK, PostgreSQL driver, pgvector client, and document/NLP libraries still used at runtime.
- [ ] Remove PyTorch and Sentence Transformers if runtime code no longer uses them after the embedding migration.

## Relational database

**Current state:** SQLite data is in `DB/training_data.db`; SQLAlchemy models coexist with direct SQLite reads.

**Planned changes:**
- [ ] Move students, mentors, teams, team members, and projects to PostgreSQL.
- [ ] Update database connection configuration.
- [ ] Replace direct `sqlite3` access in the plagiarism checker with PostgreSQL-compatible queries.

## Vector storage

**Current state:** SBERT vectors are stored in `.npy` files with metadata in JSON.

**Planned changes:**
- [ ] Enable the PostgreSQL `vector` extension.
- [ ] Store `vector(1024)` embeddings with project IDs in PostgreSQL.
- [ ] Add a cosine-similarity query and an index if the project count warrants it.

## Embeddings

**Current state:** `Models/search.py` loads `all-MiniLM-L6-v2`; `build_Index.py` creates the local index.

**Planned changes:**
- [ ] Replace runtime embedding generation with a server-side Cloudflare Workers AI request using `qwen3-embedding-0.6b`.
- [ ] Re-embed every indexed project. Existing SBERT vectors cannot be reused or mixed with Qwen vectors.

## Originality score

**Current state:** `nlp/checker.py` blends TF-IDF, LDA, and SBERT using fixed weights.

**Planned changes:**
- [ ] Use the planned lexical score plus Qwen cosine similarity.
- [ ] Normalize both signals, choose and document their weights, and tune thresholds against representative examples.
- [ ] Remove LDA and SBERT layers if they are no longer part of the design.

## Documents

**Current state:** PyMuPDF and `python-docx` extraction are already present.

**Planned changes:**
- [ ] Keep the existing extractors.
- [ ] Enforce upload size and file type limits.
- [ ] Handle empty or scanned PDFs clearly.
- [ ] Chunk long submissions sensibly before embedding.

## Authentication

**Current state:** Clerk sessions are verified by FastAPI, linked PostgreSQL profiles supply student/mentor identity, and API routes require a valid session. Browser `localStorage` holds display preferences only.

**Planned changes:**
- [x] Complete the Clerk authentication plan in `clerk-authentication-plan.md` before exposing the service publicly.
- [x] Add server-side authentication and student/mentor role checks to protected endpoints.
- [x] Require authentication for routes that expose application data.
- [x] Do not treat browser-only login state as authorization.

**Clerk production settings:**
- [ ] Create/select the Clerk production instance and use its `pk_live_` publishable key and `sk_live_` secret key.
- [ ] Set Render environment variables: `APP_ENV=production`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `CLERK_AUTHORIZED_PARTIES`, and `CORS_ALLOWED_ORIGINS`.
- [ ] Set both origin allowlists to the exact Cloudflare Pages production origin(s), including any custom frontend domain; use HTTPS origins without paths or wildcards.
- [ ] Set `Frontend/deployment-config.js` to the Render API's HTTPS origin before publishing the static frontend.
- [ ] In the Clerk production instance, configure the deployed frontend domain and its sign-in/sign-up redirect URLs. Keep the Clerk secret key only in Render's private environment settings.
- [ ] Verify HTTPS sign-in/sign-out and protected API behavior after both services are deployed.

## Deployment readiness

- [ ] Review each section above and complete the required changes before deployment.
- [ ] Verify the deployed frontend and API together.
- [ ] Keep all backend secrets in the backend host's environment settings.
