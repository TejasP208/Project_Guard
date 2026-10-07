# Merge and deployment verification — 2026-10-07

## Result

The automated regression checks and the live database/AI connectivity checks listed below pass. Public deployment is not cleared: production configuration, authoritative identity enrollment, and real browser sign-in/redirect checks remain open. This is not a claim that every browser or concurrent PostgreSQL operation has been exercised.

## Checks completed

| Check | Result |
| --- | --- |
| `venv/bin/python -m unittest discover -p 'test_*.py'` | 31 tests passed. |
| `node test_frontend_config.cjs` | Six session/configuration transport cases passed. |
| Python parsing, JavaScript syntax, inline scripts, HTML script/style references | Passed; nine external/inline JavaScript scripts checked and no missing local referenced assets. |
| `venv/bin/python -m pip check` | No broken installed requirements. A clean production dependency installation was not exercised. |
| `git diff --check` | Passed. |
| PostgreSQL read-only connection/schema check | Connection passed; required checked columns exist in projects, teams, students, mentors, and rate-limit buckets. |
| Historical comparison corpus | 72 projects, 72 without team links, zero missing vectors. No rows changed by the database check. |
| Cloudflare live request | Returned a 1,024-dimensional embedding. |
| Groq live streaming request | Returned nonempty streamed text. The configured key uses a supported alias; `GROQ_API_KEY` itself is not set locally. |
| Local NLTK resources | stopwords, wordnet, and omw-1.4 are available. Install these resources in the deployment build too. |

The backend tests cover real RS256 signature, expiry, authorized-party rejection with the installed Clerk SDK using a locally generated fixture key; protected-role boundaries; project visibility; migration rollback; mentor roster/review ownership; student team/invitation actions; full idea submission/mentor assignment/resubmission; worker JSON transport and hard timeout; and shared assignment rate-limit keys. Database tests use isolated SQLite fixtures. Real Clerk account flows and PostgreSQL concurrency/locking are not represented by those fixtures.

No connected browser tab was available for a signed-in portal check. DOM rendering, actual Clerk login, cross-domain sessions, and deployed redirects still need verification.

## Failures fixed during this check

- Plagiarism worker diagnostics polluted stdout and made the API's JSON parser reject successful checks. Worker imports/checker diagnostics now go to stderr; stdout contains only JSON.
- Roster imports previously overwrote guide labels and assigned other guides' rows to the uploading mentor. Imports now select only rows matching the authenticated mentor. A sheet with no matching rows is rejected without replacing the saved roster.
- Project assignment quotas were inadvertently divided by concrete project ID. Account/IP keys now use the shared route template.
- Project assignment now refreshes the ORM project object after acquiring its lock, so a cached pre-lock ownership value is not reused.
- Production Clerk/CORS origin parsing now explicitly rejects wildcard hosts and credential-bearing URLs.
- Old tests depended on retired caller-supplied identities/transfers and the manual plagiarism script sent a network request when imported. Regression tests now use trusted fixture profiles; the manual script runs only explicitly, with a session token and a valid TXT upload.

## Before public deployment

- Resolve `/api/profile/link` enrollment/mentor entitlement. A self-selected role or unused identifier is not proof of ownership. This previously deferred issue remains a public-deployment blocker.
- Audit existing duplicate/case-variant membership and roster identities and enforce the needed database constraints. Current row-lock protections do not repair old ambiguous data.
- Configure the actual HTTPS API origin in `Frontend/deployment-config.js`; it is currently blank for local development.
- Supply production Clerk live keys and exact HTTPS `CORS_ALLOWED_ORIGINS` / `CLERK_AUTHORIZED_PARTIES`. The local environment currently has development keys and uses the local origin defaults.
- Configure trusted reverse-proxy ranges on the host, private provider/database secrets, PostgreSQL/pgvector access, and build-time NLTK resources.
- Exercise real student and mentor sign-in, refresh, sign-out, role mismatch, create/join/invite/accept, submission, assignment, group chat, and plagiarism upload on the deployed HTTPS origins. Verify missing/expired tokens and other users' IDs fail there too.

All 72 historical projects are now hidden from mentor project lists/Axiom as intended. The portal's active list will be empty until students submit team-linked ideas or administrators provide verified legacy mappings. The historical comparison corpus remains intact.

No merge or deployment was performed.
# Follow-up deployment preparation

The user deferred enrollment entitlement until discussion with teammates and confirmed hosting URLs do not exist yet. Both remain pending. A live read-only identity audit found three duplicate membership groups; see Deploy.md for row/team IDs. No records were deleted and constraints were not applied. `identity_integrity.py --apply` refuses conflicting data and provides a transactional constraint migration after cleanup. Backend build preparation now installs NLTK resources with `sh build_backend.sh`; preprocessing no longer downloads resources during requests.
