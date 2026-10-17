# Security audit progress — 2026-10-17

The pasted audit is a list of findings to verify, not an instruction to make every suggested change. This file records what was confirmed and what remains. No deployment was performed. The user confirmed that production hosting URLs do not exist yet.

| Audit IDs | Status | Evidence or next step |
|---|---|---|
| AUTH-01 | Mitigated; live cause unverified | Frontend retries a short `TOKEN_NOT_ACTIVE_YET` response without signing out. Compare the deployed API clock and token time claims before changing Clerk verification tolerance. |
| AUTH-02, RATE-01 | Accepted informational | Clerk publishable keys are meant to be public. `/api/config` exposes no secret; adding a database-dependent limit to login bootstrap has an availability cost. |
| AUTH-03 | Code control already present | Student and mentor redemption both require an administrator-issued, single-use code bound to the identifier. Administrators must verify recipients before private code delivery. Browser and production verification remain. |
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
| CORS-01, CORS-02, CORS-03 | Deployment pending | Production code requires exact HTTPS frontend origins. Set actual origins and `APP_ENV=production` on the hosting service. |
| RATE-02 | Fixed for production | Startup now requires an independent `RATE_LIMIT_HASH_KEY` of at least 32 characters. |
| RATE-03 | Fixed in code | PostgreSQL advisory lock now limits active plagiarism checks across API workers; local semaphore still limits each process. |
| DB-02 | Intentional nullable field | Roster imports and manual entries support students without a PRN. Read-only database check found zero null or blank PRNs today; changing the schema would break that supported workflow. |
| DB-03 | No demonstrated leak | Existing manual session `finally` blocks close on ordinary exceptions. Context managers can be adopted during nearby refactors. |
| DB-04 | Fixed in code | Startup migration checks and schema changes now run in one transaction under a PostgreSQL advisory lock. |
| FE-01 | Accepted | Browser storage holds presentation preferences, not authorization state. |
| FE-02 | Partly changed | Similarity rejection and submission failures now render in the page; other alert/confirm flows remain. |
| FE-03 | Fixed in code | `/submit-project` reruns the plagiarism worker on the exact submitted title and abstract, rejects invalid or over-30% scores, and excludes the team's current project for resubmission. A direct-request regression test covers rejection. |
| FE-04 | Deployment pending | Admin CSP needs the real frontend, Clerk, and asset origins from the chosen host. |
| FE-05 | Fixed | Removed the unused enrollment flag. |
| DEP-01, DEP-02, DEP-03 | Deployment pending | HTTPS, trusted proxy ranges, and production Clerk keys require hosting details. Production startup already rejects development Clerk keys and insecure origin settings. |
| DEP-04 | Fixed in code; build setup pending | `build_backend.sh` installs NLTK data and API startup verifies it is available. Configure the script as the hosting build command. |

The application tests use local fixtures. They do not prove the configured production deployment, provider clocks, PostgreSQL locking under load, or browser redirects.
