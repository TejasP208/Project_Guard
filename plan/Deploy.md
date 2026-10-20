# Changes to Complete Before Deployment

This document tracks the project changes to complete before making Project Guard publicly available. These are planned changes, not instructions to deploy immediately.

Latest verification: see [release-check-2026-10-07.md](release-check-2026-10-07.md). Automated checks and live PostgreSQL/Groq/Cloudflare checks pass; public deployment remains blocked by identity enrollment, production configuration, and browser verification.

## Frontend hosting

**Current state:** Static files are in `Frontend/` and route API requests through `Frontend/deployment-config.js`. It uses localhost for local development and requires an explicit HTTPS API origin on deployed domains.

**Planned changes:**
- [ ] Deploy `Frontend/` to Cloudflare Pages.
- [x] Route frontend API requests through one configurable API base URL.
- [x] Add `build_frontend.py` to inject the API origin and generate the admin CSP response header; set Cloudflare Pages build command to `python build_frontend.py` and output directory to `dist`.
- [ ] Set `PROJECT_GUARD_API_BASE_URL` in the frontend build environment to the deployed API's HTTPS origin before publishing.
- [ ] Set `PROJECT_GUARD_CLERK_FAPI_HOST` to the exact Clerk Frontend API hostname before publishing, then inspect the deployed `/admin.html` response header and exercise admin sign-in and enrollment flows in a browser.
- [ ] Configure backend CORS to allow the deployed Cloudflare Pages domain.

## Backend hosting

**Current state:** FastAPI is started locally for development. Production startup now requires live Clerk keys and exact HTTPS CORS/authorized-party origins.

**Planned changes:**
- [ ] Deploy the API as a Render Web Service.
- [x] Document the backend build command as `sh build_backend.sh`.
- [ ] Use start command `uvicorn main:app --host 0.0.0.0 --port $PORT` on Render.
- [ ] Store Groq and Cloudflare credentials in Render environment settings; do not put them in frontend code.
- [ ] Account for the possibility that Render's free web services sleep while idle.
- [ ] Configure `TRUSTED_PROXY_IPS` with the hosting provider's documented proxy CIDRs before relying on client-IP rate limits. Do not trust forwarded IP headers from arbitrary clients.
- [ ] Keep public deployment blocked until both frontend and API are served over HTTPS and the exact deployed origins are configured.

**Production environment values:** Set these in the backend provider's private environment settings. `APP_ENV=production`; `DATABASE_URL`; live `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY`; identical exact HTTPS frontend origin lists in `CLERK_AUTHORIZED_PARTIES` and `CORS_ALLOWED_ORIGINS`; independent random `RATE_LIMIT_HASH_KEY` with at least 32 characters; and provider-documented `TRUSTED_PROXY_IPS`. Keep `GROQ_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `ENROLLMENT_ADMIN_CLERK_USER_IDS`, and optional `CLERK_JWT_KEY` private as well. Production startup checks all required keys/settings, HTTPS origins, matching origin lists, proxy ranges, and the independent rate-limit key. Do not copy example or development values into production.

## Dependencies

**Current state:** A fresh temporary Python 3.14.7 environment on macOS ARM installed `requirements.txt` successfully, `pip check` reported no broken requirements, and backend import plus NLTK preprocessing checks passed. This is not the intended production host or operating system. Dependencies are not locked and the set still includes PyTorch/Sentence Transformers for the SQLite checker fallback and legacy indexing/manual tools.

**Planned changes:**
- [x] Make the backend build check declared dependencies with `pip check`, download NLTK resources, validate preprocessing, and import `main`.
- [ ] Exercise a clean installation and startup on the selected backend host and its Python version.
- [ ] Decide whether to retain the SQLite checker fallback and legacy index/manual tools before removing PyTorch/Sentence Transformers and their exclusive dependencies.

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

**Current state:** The PostgreSQL checker combines TF-IDF (60%) and Qwen similarity (40%). Students must check their title, abstract, and document before submitting the same content. Scores above 30% are blocked. These weights and cutoff have not been calibrated because `embeddings/labeled_cases.csv` has no labeled cases; evaluate false positives and false negatives before relying on the score as a plagiarism finding. The calibration script evaluates the configured weights; it does not optimize them. LDA/SBERT remain in the legacy SQLite fallback.

**Planned changes:**
- [x] Use the planned lexical score plus Qwen cosine similarity in the active PostgreSQL checker.
- [ ] Collect representative labeled cases, evaluate and document the weights and 30% cutoff (including held-out examples), then adjust the submission policy if needed.
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
- [ ] Complete the production configuration and live-browser verification in `clerk-authentication-plan.md` before exposing the service publicly. Follow `enrollment-operations.md` for recipient verification and private code delivery.
- [ ] Complete every applicable check in `runtime-verification-checklist.md` on staging with at least two backend workers before public release.
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
- [ ] Set Render environment variables: `APP_ENV=production`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `CLERK_AUTHORIZED_PARTIES`, `CORS_ALLOWED_ORIGINS`, and an independent random `RATE_LIMIT_HASH_KEY` of at least 32 characters.
- [ ] Set both origin allowlists to the exact Cloudflare Pages production origin(s), including any custom frontend domain; use HTTPS origins without paths or wildcards.
- [ ] Set `Frontend/deployment-config.js` to the Render API's HTTPS origin before publishing the static frontend.
- [ ] In the Clerk production instance, configure the deployed frontend domain and its sign-in/sign-up redirect URLs. Keep the Clerk secret key only in Render's private environment settings.
- [ ] Verify HTTPS sign-in/sign-out and protected API behavior after both services are deployed.
- [ ] Install NLTK resources in the backend build: `python -m nltk.downloader stopwords wordnet omw-1.4`. Verify they are available to the runtime user and set `NLTK_DATA` if using a custom data directory.

## Deployment readiness

### October 7 preparation and pending decisions

- Student and mentor enrollment now require administrator-issued, single-use, identity-bound codes. Administrators must verify recipients and deliver codes privately; real Clerk browser flows still need deployment verification.
- Hosting has not been created. HTTPS frontend/API URLs, live Clerk keys, exact origin allowlists, and proxy ranges remain pending. Do not substitute example domains into active configuration.
- When hosting is created, deploy the backend first, then the static frontend with `PROJECT_GUARD_API_BASE_URL` set to that backend's public HTTPS origin and `PROJECT_GUARD_CLERK_FAPI_HOST` set to the exact Clerk Frontend API hostname. Add the final frontend origin to both backend origin variables and Clerk's production allowed domains/redirect URLs. Rebuild the frontend after the API and Clerk origins are known. `build_frontend.py` writes only into its output directory, places only the public API origin in browser assets, and emits a restrictive CSP for `/admin.html`.
- Use `sh build_backend.sh` as the backend build command. It installs requirements and NLTK corpora and checks preprocessing. Request workers no longer download corpora on import. Set `NLTK_DATA` to a location shared by build and runtime if the host uses separate users/directories.
- Run `python identity_integrity.py` for a read-only identity audit. After administrator-reviewed cleanup, run `python identity_integrity.py --apply`. It locks the affected tables, audits again, and atomically adds normalized unique indexes, nonblank identity checks, and team membership/invitation foreign keys. It does not delete or choose records.
- The migration does not enforce cross-table Clerk subject uniqueness or title-alias mentor uniqueness in PostgreSQL; the audit detects these and application identity resolution remains required. Re-run the audit before release. Production startup does not automatically apply this migration.
- Live audit: 3 student profiles, 1 mentor profile, 16 memberships, 132 roster rows, 0 invitations. Three duplicate membership groups block migration: rows 1/2 (teams 1/4), rows 5/6/8/9/10/11 (teams 11/12/13/13/14/15), rows 7/12/13 (teams 12/16/16). All other audit conflict categories were empty. No database rows or constraints were changed.
- The mentor portal now has a separate **Replace All Teams** workbook action. It validates the complete group sheet, asks for an explicit group choice when a PRN appears twice, then replaces team memberships, invitations, and mentor roster rows in one transaction. Existing student-submitted projects stay attached to their original teams. A project team that cannot be mapped safely to a sheet group blocks the import. Chat and scheduled review history for changed groups is archived out of the current room to prevent access by new members. The demo workbook has PRN `124A9023` in Groups 1 and 12; the authoritative choice supplied for this upload is Group 12. Uploading the demo workbook to the configured database has not been performed.
- Production secret storage, private PostgreSQL/pgvector access, trusted proxy configuration, and deployed sign-in/workflow checks remain pending until hosting exists.

- [ ] Review each section above and complete the required changes before deployment.
- [ ] Verify the deployed frontend and API together.
- [ ] Keep all backend secrets in the backend host's environment settings.
