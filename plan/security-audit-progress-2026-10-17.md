# Security audit progress — 2026-10-17

The pasted audit is a list of findings to verify, not an instruction to make every suggested change. This file records what was confirmed and what remains. No deployment was performed. The user confirmed that production hosting URLs do not exist yet.

| Audit IDs | Status | Evidence or next step |
|---|---|---|
| AUTH-01 | Mitigated; live cause unverified | Frontend retries a short `TOKEN_NOT_ACTIVE_YET` response without signing out. Compare the deployed API clock and token time claims before changing Clerk verification tolerance. |
| AUTH-02, RATE-01 | Accepted informational | Clerk publishable keys are meant to be public. `/api/config` exposes no secret; adding a database-dependent limit to login bootstrap has an availability cost. |
| AUTH-03 | Issuance audit and operating procedure added; deployment pending | Admin issuance now requires verification attestation and method; issuer Clerk ID and method are stored with the hashed, single-use, maximum-seven-day code. `plan/enrollment-operations.md` defines verification and private delivery. Real recipient verification and HTTPS browser flows remain operational release steps. |
| AUTH-04 | Already enforced | The portal guard replaces the entire body on role mismatch; backend profile-role checks block mismatched API actions. Keeping the Clerk session lets users open the correct portal. |
| AUTH-05 | Changed | Portal session restoration now waits up to about 10 seconds. |
| AUTH-06 | Changed | The admin page clears a displayed code after five minutes or portal switch. |
| AUTH-07 | Deployment pending | The actual HTTPS API URL has not been supplied; the frontend deliberately fails with a configuration error on a nonlocal origin until set. |
| AUTH-08 | Fixed in code and configured PostgreSQL | Removed unused ORM password fields and dropped the retired columns after a count-only preview. A second inspection found no remaining password columns. |
| ACL-01, DB-01 | Pending by user choice | Read-only audit confirms three duplicate membership groups. User chose to leave cleanup pending. `identity_integrity.py --apply` will refuse until reviewed rows are resolved. |
| ACL-02 | Verified | Middleware first verifies the Clerk session token, then checks the subject against the server-side admin ID allowlist. Existing tests deny an outsider. |
| ACL-03 | Fixed | Account deletion now looks up a profile by its verified Clerk subject directly. |
| ACL-04 | Read-only audit clean | `is_own` is display metadata, not authorization. All three historical message senders matched exactly one current profile; no unmatched or ambiguous identifiers were found. |
| ACL-05 | Existing protection | Legacy projects remain excluded from mentor list and Axiom paths; visibility tests cover this. Continue adding route tests. |
| CORS-01, CORS-02, CORS-03 | Code gate strengthened; deployment pending | Production startup requires exact HTTPS frontend origins and now requires the CORS and Clerk authorized-party origin sets to match. Set the real origins and `APP_ENV=production` on the hosting service after it is created. |
| RATE-02 | Fixed for production | Startup requires an independent `RATE_LIMIT_HASH_KEY` of at least 32 characters and rejects reuse of either Clerk key. |
| RATE-03 | Fixed in code | PostgreSQL advisory lock now limits active plagiarism checks across API workers; local semaphore still limits each process. |
| DB-02 | Intentional nullable field | Roster imports and manual entries support students without a PRN. Read-only database check found zero null or blank PRNs today; changing the schema would break that supported workflow. |
| DB-03 | Fixed for main.py | All endpoint sessions in `main.py` now use `with SessionLocal()`. The Axiom rejection path has a session-close regression test. |
| DB-04 | Fixed in code | Startup migration checks and schema changes now run in one transaction under a PostgreSQL advisory lock. |
| FE-01 | Accepted | Browser storage holds presentation preferences, not authorization state. |
| FE-02 | Replaced in code; browser accessibility review pending | Student, mentor, and admin actions now use a visible live-region notification and a keyboard-operable native confirmation dialog instead of browser alerts/confirms. Field-specific submission errors remain inline. Verify keyboard/screen-reader behavior in the deployed browsers. |
| FE-03 | Fixed in code | `/submit-project` reruns the plagiarism worker on the exact submitted title and abstract, rejects invalid scores, and excludes the team's current project for resubmission. Hard blocking is disabled until a calibrated `ORIGINALITY_BLOCK_THRESHOLD` is configured; similarity scores remain advisory meanwhile. |
| FE-04 | Build-time policy added; deployment verification pending | `build_frontend.py` emits an admin-only CSP using the exact API and Clerk Frontend API hosts. Script sources are restricted, object/frame embedding is blocked, and inline script/eval are not allowed; Clerk requires inline styles for runtime UI. Verify the deployed header and admin flow after real origins are known. |
| FE-05 | Fixed | Removed the unused enrollment flag. |
| DEP-01, DEP-02, DEP-03 | Code preparation complete; deployment pending | Production startup rejects development Clerk keys and insecure/mismatched origins. `build_frontend.py` injects the public API HTTPS origin into the static build. Actual frontend/API URLs, live Clerk keys, provider proxy CIDRs, secrets, HTTPS startup, and CORS/browser verification still require hosting to be created. |
| DEP-04 | Local clean-install check passed; host verification pending | A fresh Python 3.14.7/macOS ARM environment installed requirements, passed `pip check`, imported `main`, and passed the NLTK preprocessing smoke check. `build_backend.sh` now repeats those checks. The production host is not selected, and PyTorch/Sentence Transformers remain until the SQLite fallback/tools decision is made. |
| REL-01 | Checklist prepared; runtime verification pending | `plan/runtime-verification-checklist.md` covers staging browser/auth, PostgreSQL multi-worker writes and plagiarism locking, proxy IP trust, uploads, provider calls, and CORS. No deployed flow was run because hosting does not exist yet. |

The application tests use local fixtures. They do not prove the configured production deployment, provider clocks, PostgreSQL locking under load, or browser redirects.
