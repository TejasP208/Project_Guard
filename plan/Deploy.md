# Changes to Complete Before Deployment

This document tracks the project changes to complete before making Project Guard publicly available. These are planned changes, not instructions to deploy immediately.

Latest verification: see [release-check-2026-10-07.md](release-check-2026-10-07.md). Automated checks and live PostgreSQL/Groq/Cloudflare checks pass; public deployment remains blocked by identity enrollment, production configuration, and browser verification.

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
- [ ] Configure `TRUSTED_PROXY_IPS` with the hosting provider's documented proxy CIDRs before relying on client-IP rate limits. Do not trust forwarded IP headers from arbitrary clients.
- [ ] Keep public deployment blocked until both frontend and API are served over HTTPS and the exact deployed origins are configured.

## Dependencies

**Current state:** `requirements.txt` may not clearly declare every imported runtime dependency.

**Planned changes:**
- [ ] Make the dependency list self-contained, including FastAPI, Uvicorn, SQLAlchemy, Passlib, `python-multipart`, the Groq SDK, PostgreSQL driver, pgvector client, and document/NLP libraries still used at runtime.
- [ ] Remove PyTorch and Sentence Transformers if runtime code no longer uses them after the embedding migration.

## Relational database

**Current state:** PostgreSQL stores active teams, memberships, projects, and shared rate-limit buckets. New team projects use a stable `team_id` relationship with one current project per team; legacy projects without a team link are retained. SQLite data remains in `DB/training_data.db` for the import/checker workflow.

**Planned changes:**
- [x] Move students, mentors, teams, team members, and projects to PostgreSQL.
- [ ] Update database connection configuration.
- [x] Replace direct `sqlite3` access in the active plagiarism checker with PostgreSQL-compatible queries.

## Vector storage

**Current state:** Active project embeddings use PostgreSQL `vector(1024)`. Local SBERT artifacts remain for legacy/manual tools. The read-only release check found 72 projects and no missing vectors.

**Planned changes:**
- [x] Enable the PostgreSQL `vector` extension.
- [x] Store `vector(1024)` embeddings with project IDs in PostgreSQL.
- [ ] Add a cosine-similarity query and an index if the project count warrants it.

## Embeddings

**Current state:** `Models/search.py` loads `all-MiniLM-L6-v2`; `build_Index.py` creates the local index.

**Planned changes:**
- [x] Replace active PostgreSQL runtime embedding generation with a server-side Cloudflare Workers AI request using `qwen3-embedding-0.6b`.
- [ ] Re-embed every indexed project. Existing SBERT vectors cannot be reused or mixed with Qwen vectors.

## Originality score

**Current state:** The PostgreSQL checker combines TF-IDF (60%) and Qwen similarity (40%). LDA/SBERT remain in the legacy SQLite fallback. Threshold calibration remains separate from release connectivity checks.

**Planned changes:**
- [x] Use the planned lexical score plus Qwen cosine similarity in the active PostgreSQL checker.
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
- [ ] Complete the production configuration, authoritative enrollment, and live-browser verification in `clerk-authentication-plan.md` before exposing the service publicly.
- [x] Add server-side authentication and student/mentor role checks to protected endpoints.
- [x] Require authentication for routes that expose application data.
- [x] Do not treat browser-only login state as authorization.

## Team idea and mentor assignment workflow

- [x] Students submit an idea for a team only after at least two students have joined.
- [x] Resubmitting overwrites the team's current project idea while preserving membership and mentor assignment.
- [x] Mentors can browse team ideas and assign themselves to an unassigned team; each project has at most one assigned mentor.
- [x] Roster re-import updates the importing mentor's roster fields and preserves the student's canonical submitted project title.
- [x] Roster import validates the complete sheet, then replaces the importing mentor's current roster; rows omitted from the upload are removed.

**Clerk production settings:**
- [ ] Create/select the Clerk production instance and use its `pk_live_` publishable key and `sk_live_` secret key.
- [ ] Set Render environment variables: `APP_ENV=production`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `CLERK_AUTHORIZED_PARTIES`, and `CORS_ALLOWED_ORIGINS`.
- [ ] Set both origin allowlists to the exact Cloudflare Pages production origin(s), including any custom frontend domain; use HTTPS origins without paths or wildcards.
- [ ] Set `Frontend/deployment-config.js` to the Render API's HTTPS origin before publishing the static frontend.
- [ ] In the Clerk production instance, configure the deployed frontend domain and its sign-in/sign-up redirect URLs. Keep the Clerk secret key only in Render's private environment settings.
- [ ] Verify HTTPS sign-in/sign-out and protected API behavior after both services are deployed.
- [ ] Install NLTK resources in the backend build: `python -m nltk.downloader stopwords wordnet omw-1.4`. Verify they are available to the runtime user and set `NLTK_DATA` if using a custom data directory.

## Deployment readiness

### October 7 preparation and pending decisions

- Student enrollment now requires an administrator-issued single-use code; see `student-enrollment.md` for private terminal commands. Mentor enrollment entitlement remains deferred and blocks public deployment. Earlier enrollment deferral is superseded for students by this implementation.
- Hosting has not been created. HTTPS frontend/API URLs, live Clerk keys, exact origin allowlists, and proxy ranges remain pending. Do not substitute example domains into active configuration.
- Use `sh build_backend.sh` as the backend build command. It installs requirements and NLTK corpora and checks preprocessing. Request workers no longer download corpora on import. Set `NLTK_DATA` to a location shared by build and runtime if the host uses separate users/directories.
- Run `python identity_integrity.py` for a read-only identity audit. After administrator-reviewed cleanup, run `python identity_integrity.py --apply`. It locks the affected tables, audits again, and atomically adds normalized unique indexes, nonblank identity checks, and team membership/invitation foreign keys. It does not delete or choose records.
- The migration does not enforce cross-table Clerk subject uniqueness or title-alias mentor uniqueness in PostgreSQL; the audit detects these and application identity resolution remains required. Re-run the audit before release. Production startup does not automatically apply this migration.
- Live audit: 3 student profiles, 1 mentor profile, 16 memberships, 132 roster rows, 0 invitations. Three duplicate membership groups block migration: rows 1/2 (teams 1/4), rows 5/6/8/9/10/11 (teams 11/12/13/13/14/15), rows 7/12/13 (teams 12/16/16). All other audit conflict categories were empty. No database rows or constraints were changed.
- Production secret storage, private PostgreSQL/pgvector access, trusted proxy configuration, and deployed sign-in/workflow checks remain pending until hosting exists.

- [ ] Review each section above and complete the required changes before deployment.
- [ ] Verify the deployed frontend and API together.
- [ ] Keep all backend secrets in the backend host's environment settings.
