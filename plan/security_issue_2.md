# Project Guard — Security Issues Audit
**Audit Date:** 2026-10-17  
**Scope:** Full project review — Backend (`main.py`, `clerk_auth.py`, `group_connect.py`, `models.py`, `database.py`), Frontend (all HTML/JS files), and deployment configuration.

---

## 🔐 Section 1 — Login & Authentication Issues

### ISSUE-AUTH-01 · `TOKEN_NOT_ACTIVE_YET` Clock-Skew Rejection (Known Incident)
- **Severity:** High
- **File:** [`auth-retry.js`](../Frontend/auth-retry.js), [`portal-session-guard.js`](../Frontend/portal-session-guard.js), [`plan/auth-token-timing-incident.md`](auth-token-timing-incident.md)
- **Description:** A newly issued Clerk JWT token's `nbf` (not-before) field can be later than the API server's current clock. This causes the server to reject fresh login tokens with `TOKEN_NOT_ACTIVE_YET`, which in turn signs the user out and shows a "Portal unavailable" screen immediately after login.
- **Root cause:** API host clock is out of sync with Clerk's token issuance time. The frontend retries for up to 7 seconds with exponential backoff (`1s → 2s → 4s`) but cannot fix a permanently drifted server clock.
- **Current mitigation:** `auth-retry.js` retries only `TOKEN_NOT_ACTIVE_YET` rejections. Session is preserved across retries.
- **Remaining action needed:**
  - Verify and sync API host clock (NTP) on the deployment server.
  - Compare token `iat`, `nbf`, `exp` against server UTC time in dev tools to confirm.
  - This is NOT fixed — only mitigated at the frontend.

---

### ISSUE-AUTH-02 · Unauthenticated `/api/config` Exposes Clerk Publishable Key
- **Severity:** Low / Informational
- **File:** [`main.py`](../main.py) (`/api/config` endpoint), [`clerk-config.js`](../Frontend/clerk-config.js)
- **Description:** The `/api/config` endpoint is intentionally public and returns the Clerk publishable key to bootstrap the frontend. While the publishable key is safe to expose (by Clerk design), this endpoint is fully unauthenticated and does not log callers.
- **Risk:** Can be polled by scanners to fingerprint the Clerk application. No secrets are leaked.
- **Action:** Add rate limiting to `/api/config` to prevent automated scanning/enumeration. Currently excluded from rate limiting.

---

### ISSUE-AUTH-03 · Self-Selected Identity at Profile Registration — Critical Open Blocker
- **Severity:** Critical
- **File:** [`main.py`](../main.py) (`/api/profile/link`), [`plan/Security.md`](Security.md)
- **Description:** When a new student or mentor registers via `/api/profile/link`, they can supply any roll number or mentor name as their identity. Clerk only proves the caller controls *that Clerk account* — it does **not** prove ownership of the claimed roll number or mentor identity.
- **Impact:** An attacker can register with a fabricated or stolen roll number (e.g., `CS2023001`) and claim that identity in the system before the real student does.
- **Current mitigation:** Student enrollment now requires a single-use code (from `enrollment.py`). The code is bound to a specific roll number and expires.
- **Remaining gap:** Mentor enrollment entitlement is **still unverified** — a mentor can self-select any name that matches an admin-issued code, but the code-to-name binding for mentors needs production verification. Existing profiles without codes are retained (legacy).
- **Status:** **Public deployment blocker** — explicitly flagged in `Security.md` and `release-check-2026-10-07.md`.

---

### ISSUE-AUTH-04 · Portal Role Mismatch Does Not Always Sign Out
- **Severity:** Medium
- **File:** [`auth.js`](../Frontend/auth.js), [`portal-session-guard.js`](../Frontend/portal-session-guard.js)
- **Description:** When a user authenticated as a mentor tries to open the student portal (or vice versa), the system shows an error message. However, the Clerk session is only signed out in `auth.js` on a 401 without `TOKEN_NOT_ACTIVE_YET`. In `portal-session-guard.js`, the role mismatch is shown as an error with a link to the correct portal — but the session remains active.
- **Risk:** A user switching between portals may see stale state or be able to manually navigate to the wrong portal's pages if session guard fails to load (e.g., JavaScript error).
- **Action:** Ensure that `portal-session-guard.js` fully blocks page rendering (already partially done via `document.documentElement.style.visibility = 'hidden'`) and clears the body on mismatch.

---

### ISSUE-AUTH-05 · Clerk Session State Can Briefly Lag After Redirect
- **Severity:** Medium
- **File:** [`portal-session-guard.js`](../Frontend/portal-session-guard.js)
- **Description:** `getSettledSessionToken` polls up to 30 times (× 100ms = 3 seconds) to wait for a valid Clerk token after a redirect. This is a best-effort workaround for Clerk SDK timing issues.
- **Risk:** On slow connections or cold starts, the 3-second window may not be enough, causing the user to be erroneously shown "Clerk has no active session on this portal — Sign in again" after a successful login redirect.
- **Action:** Consider extending the polling window or implementing a proper Clerk-ready event listener if the SDK exposes one.

---

### ISSUE-AUTH-06 · Enrollment Code Exposed in Browser After Generation
- **Severity:** Medium
- **File:** [`admin.html`](../Frontend/admin.html), [`admin.js`](../Frontend/admin.js)
- **Description:** After an enrollment code is generated by an admin, it is displayed in plaintext in the DOM (`<code id="code">`) and persists in the page until navigation. The DOM element is readable by any browser extension or injected script while the tab is open.
- **Risk:** The code is shown only once as intended, but if the admin's browser is compromised (malicious extension, XSS), the code can be exfiltrated.
- **Action:** Auto-clear the displayed code after a timeout (e.g., 5 minutes), or add a warning to close the admin tab after copying.

---

### ISSUE-AUTH-07 · `deployment-config.js` Has Blank `PROJECT_GUARD_API_BASE_URL`
- **Severity:** High (deployment risk)
- **File:** [`deployment-config.js`](../Frontend/deployment-config.js)
- **Description:** `window.PROJECT_GUARD_API_BASE_URL` is set to an empty string `''`. In production, if this is not updated before deploying the frontend, `clerk-config.js` will throw: *"Set PROJECT_GUARD_API_BASE_URL to the deployed HTTPS API origin in deployment-config.js."* — completely breaking the login page.
- **Risk:** Entire auth flow breaks silently unless the deployment step explicitly sets this value.
- **Action:** This must be set to the live Render/Cloudflare Pages API URL before every production deploy. Document this in a deployment checklist.

---

### ISSUE-AUTH-08 · Password Stored in DB But No Longer Used (Legacy Residue)
- **Severity:** Medium
- **File:** [`models.py`](../models.py), `migrate_sqlite_to_postgres.py`
- **Description:** The `Student`, `Mentor`, and `Team` models still have a `password` column. Password-based login routes (`/login`, `/signup`, `/mentor/login`, `/mentor/signup`) return HTTP 410 Gone. However, hashed passwords may still exist in the database for legacy accounts created before the Clerk migration.
- **Risk:** Old bcrypt hashes sitting in the database are an unnecessary attack surface. If the DB is breached, old password hashes could be cracked offline.
- **Action:** Drop the `password` column from `students`, `mentors`, and `teams` tables after confirming no legacy code reads it. Add a migration step to zero-out then remove these columns.

---

## 🛡️ Section 2 — Authorization & Access Control Issues

### ISSUE-ACL-01 · No Database-Level Uniqueness Constraint on `team_members.roll_no`
- **Severity:** High
- **File:** [`models.py`](../models.py), [`main.py`](../main.py)
- **Description:** `TeamMember` has no `UniqueConstraint` on `roll_no`. The application-level check (`WITH FOR UPDATE`) prevents concurrent duplicates under normal operation, but does not prevent:
  - Duplicate or case-variant entries that may already exist from legacy data.
  - Race conditions across multiple API workers if the row-lock is not perfectly atomic.
- **Impact:** A student could appear in multiple teams, bypassing team membership limits and causing inconsistencies in project assignment and invitation access.
- **Action:** Apply a DB-level `UNIQUE (roll_no)` constraint on `team_members` after cleaning the three duplicate membership groups identified in `Deploy.md`. `identity_integrity.py --apply` is provided but not yet run.

---

### ISSUE-ACL-02 · Admin Portal Has No Role Enforcement on Backend (`/api/admin/*`)
- **Severity:** High
- **File:** [`main.py`](../main.py) (`require_enrollment_admin`), [`admin.html`](../Frontend/admin.html)
- **Description:** The admin panel at `/api/admin/*` calls `require_enrollment_admin(request)` in the middleware. However, the implementation of `require_enrollment_admin` is not visible in the reviewed code excerpt — if this relies solely on a specific Clerk user ID or an environment variable comparison without cryptographic verification, it could be bypassed.
- **Action:** Confirm `require_enrollment_admin` enforces a non-guessable, server-side secret or a verified Clerk organization membership. Ensure the admin API cannot be accessed with a regular student/mentor Clerk token.

---

### ISSUE-ACL-03 · `delete_profile_account` Uses Conditional Logic That May Miss Profile
- **Severity:** Medium
- **File:** [`main.py`](../main.py) (`delete_profile_account` function)
- **Description:** The query uses `Student.id == profile["id"] if "id" in profile else Student.clerk_user_id == clerk_user_id`. The profile dict returned by `resolve_profile_for_clerk_user_id` does **not** include an `"id"` field — it only returns `role`, `identifier`, and `year`. So the code always falls through to the `clerk_user_id` lookup. The conditional is dead code that adds confusion but does not cause a security bug currently.
- **Action:** Simplify the query to always use `clerk_user_id` since the profile dict never contains an `id` field.

---

### ISSUE-ACL-04 · Group Chat — `sender_user` Not Validated Against Clerk Profile
- **Severity:** Medium
- **File:** [`group_connect.py`](../group_connect.py)
- **Description:** In `send_message`, `sender_user` is set to `account.username` (mentor) or `account.roll_no` (student) — both sourced from the DB after verifying the Clerk profile. However, `is_own` is computed at read time by comparing `message.sender_user` against the current user's identifier. If a past message has a `sender_user` value that case-folds to match a different user's identifier (due to legacy data), they could see someone else's message marked as `is_own`.
- **Action:** Add a uniqueness audit for `sender_user` values in historical `group_messages` rows.

---

### ISSUE-ACL-05 · Legacy Projects Without Team Link Are Not Deleted — Corpus Exposure
- **Severity:** Low / Informational
- **File:** [`project_access.py`](../project_access.py), [`legacy_projects.py`](../legacy_projects.py)
- **Description:** 72 legacy projects without team relationships are hidden from the mentor portal but retained as a plagiarism comparison corpus. If `project_access.py` filtering logic changes or a new endpoint is added without calling `mentor_projects()`, these projects could be re-exposed.
- **Action:** Add a test for every new project-returning endpoint to verify legacy rows are excluded. Consider archiving the legacy corpus in a separate read-only table.

---

## 🌐 Section 3 — CORS & Transport Issues

### ISSUE-CORS-01 · `CORS_ALLOWED_ORIGINS` Not Set in Production Deployment Yet
- **Severity:** High
- **File:** [`main.py`](../main.py), [`plan/Security.md`](Security.md)
- **Description:** The backend requires `CORS_ALLOWED_ORIGINS` to be set with exact HTTPS origins for production. If this env variable is missing at deployment, the startup will raise `RuntimeError: CORS_ALLOWED_ORIGINS must list the deployed HTTPS frontend origin(s).` — crashing the API.
- **Action:** Set `CORS_ALLOWED_ORIGINS` in the Render environment before deploying. Document this alongside `CLERK_AUTHORIZED_PARTIES` in the deployment checklist.

---

### ISSUE-CORS-02 · `CLERK_AUTHORIZED_PARTIES` Not Set for Production
- **Severity:** High
- **File:** [`clerk_auth.py`](../clerk_auth.py)
- **Description:** In production, `_authorized_parties()` raises HTTP 503 if `CLERK_AUTHORIZED_PARTIES` is not configured. This means any unset deployment will fail all authenticated requests.
- **Action:** Same as above — configure in Render/deployment secrets before launch.

---

### ISSUE-CORS-03 · Local Dev Origins (`http://127.0.0.1:5500`) Hard-Coded as Fallback
- **Severity:** Low
- **File:** [`clerk_auth.py`](../clerk_auth.py), [`main.py`](../main.py)
- **Description:** Development CORS and authorized parties default to `http://127.0.0.1:5500` and `http://localhost:5500`. If `APP_ENV` is not correctly set in a staging/QA environment, these permissive dev origins could apply to a non-local deployment.
- **Action:** Explicitly set `APP_ENV=production` and `RENDER=true` in all non-local environments to ensure the production code path is enforced.

---

## 🔑 Section 4 — Rate Limiting & Abuse Protection Issues

### ISSUE-RATE-01 · `/api/config` Has No Rate Limit
- **Severity:** Low
- **File:** [`main.py`](../main.py)
- **Description:** The public `/api/config` endpoint is excluded from all rate limiting. An attacker can poll this endpoint to fingerprint the Clerk application or to keep the server warm.
- **Action:** Add a basic IP-level rate limit on `/api/config`.

---

### ISSUE-RATE-02 · `RATE_LIMIT_HASH_KEY` Falls Back to `CLERK_SECRET_KEY`
- **Severity:** Medium
- **File:** [`main.py`](../main.py) (`_rate_bucket_key`)
- **Description:** If `RATE_LIMIT_HASH_KEY` is not set, the HMAC for rate limit bucket keys falls back to using `CLERK_SECRET_KEY`. While this is a functional fallback, it means:
  - Rotating `CLERK_SECRET_KEY` will invalidate all current rate limit buckets (treating all users as under a new window).
  - The secret key is used for two distinct security purposes — increasing the blast radius if it is ever compromised.
- **Action:** Set a dedicated `RATE_LIMIT_HASH_KEY` environment variable in production. Do not rely on the fallback.

---

### ISSUE-RATE-03 · Plagiarism Semaphore is Per-Process, Not Shared
- **Severity:** Medium
- **File:** [`main.py`](../main.py)
- **Description:** `_plagiarism_semaphore = asyncio.Semaphore(1)` is an in-process semaphore. With multiple API workers (e.g., Gunicorn with 4 workers), up to 4 plagiarism checks can run concurrently — one per worker — bypassing the intended single-check limit.
- **Action:** Use PostgreSQL-backed advisory locks or a Redis-based semaphore for cross-worker concurrency control.

---

## 🗃️ Section 5 — Database & Data Integrity Issues

### ISSUE-DB-01 · Duplicate Team Membership Rows in Live Database
- **Severity:** High
- **File:** [`models.py`](../models.py), [`plan/release-check-2026-10-07.md`](release-check-2026-10-07.md)
- **Description:** A live audit found **3 duplicate membership groups** in `team_members` (same student in multiple teams). No uniqueness constraint exists on `team_members.roll_no`. `identity_integrity.py --apply` is available but **has not been executed**.
- **Impact:** Students in duplicate memberships may be able to bypass "already in a team" checks, invite others into multiple groups, or trigger inconsistencies in project assignment.
- **Action:** Clean duplicate rows and run `identity_integrity.py --apply` to enforce the uniqueness constraint. This is a pre-launch requirement.

---

### ISSUE-DB-02 · `MentorStudent.prn` Can Be NULL — Breaks Roster Lookups
- **Severity:** Medium
- **File:** [`models.py`](../models.py), [`main.py`](../main.py)
- **Description:** `MentorStudent.prn` is nullable. Several roster lookups (e.g., in `assign_project_to_current_mentor`) filter with `func.lower(MentorStudent.prn).in_(...)`. If `prn` is NULL, those rows are silently excluded from the lookup, meaning students without a PRN in the roster are invisible to project assignment.
- **Action:** Add a NOT NULL constraint on `prn` (after data cleanup), or explicitly handle NULL PRNs in roster logic.

---

### ISSUE-DB-03 · Session Not Used as Context Manager in Several Endpoints
- **Severity:** Medium
- **File:** [`main.py`](../main.py)
- **Description:** Many endpoints use `db = SessionLocal()` with manual `db.close()` in a `finally` block, but NOT the context manager form (`with SessionLocal() as db`). If an unexpected exception escapes before the `finally` block (e.g., a `BaseException` like `KeyboardInterrupt`), the session could leak.
- **Action:** Refactor all endpoint DB usage to use `with SessionLocal() as db:` consistently, as already done in `group_connect.py`.

---

### ISSUE-DB-04 · `migrate_database()` Uses Raw `exec_driver_sql` Without Idempotency Checks for All Paths
- **Severity:** Low
- **File:** [`database.py`](../database.py)
- **Description:** Some migration steps (`ALTER TABLE ... ADD COLUMN`) are wrapped in `if "column_name" not in columns` checks, but this runs on every startup. If the database is under concurrent load during a rolling restart, two workers could both check for the column's absence and both attempt the `ALTER TABLE`, causing one to fail.
- **Action:** Wrap migrations in a PostgreSQL advisory lock or use a proper migration framework (e.g., Alembic).

---

## 🖥️ Section 6 — Frontend Security Issues

### ISSUE-FE-01 · `localStorage` Used for Display Name and Avatar (Non-Sensitive but Not Validated on Load)
- **Severity:** Low
- **File:** [`script.js`](../Frontend/script.js), [`mentor_script.js`](../Frontend/mentor_script.js)
- **Description:** `localStorage.getItem('studentName')` and `localStorage.getItem('studentPic')` are used for display purposes. The avatar is validated with `isSafeAvatarDataUrl()` before rendering. However, `studentName` is set directly as `textContent` (safe from XSS), so the risk is low.
- **Risk:** A browser extension or XSS vulnerability on any page could overwrite `localStorage` to display arbitrary names/images. No sensitive auth data is stored here.
- **Action:** This is acceptable for display preferences. Continue not using `localStorage` for any authentication or authorization data.

---

### ISSUE-FE-02 · `alert()` Used for Security-Relevant Messages
- **Severity:** Low
- **File:** [`script.js`](../Frontend/script.js), [`mentor_script.js`](../Frontend/mentor_script.js)
- **Description:** Several action flows (team join, team leave, plagiarism threshold breach, submission failure) use `alert()` / `confirm()` for user feedback. `alert()` and `confirm()` can be suppressed by browser settings or extensions, causing the user to miss critical security messages (e.g., "Plagiarism score of 45% exceeds the 30% limit — submission blocked").
- **Action:** Replace `alert()`/`confirm()` with in-DOM feedback elements, especially for security-relevant messages (plagiarism threshold breach, session expiry).

---

### ISSUE-FE-03 · Plagiarism Gate Can Be Bypassed by Direct API Call
- **Severity:** Medium
- **File:** [`script.js`](../Frontend/script.js), [`main.py`](../main.py)
- **Description:** The 30% plagiarism threshold that disables the "Submit" button (`btnSubmit.disabled = true`) is enforced **only on the frontend**. The `/submit-project` backend endpoint does **not** check the plagiarism score before accepting a submission.
- **Impact:** A student can submit a high-plagiarism project by calling `/submit-project` directly (e.g., via `curl` or browser DevTools) without ever running `/check-plagiarism`.
- **Action:** The backend should either enforce a maximum plagiarism score at submission time, or require a signed/timestamped attestation from the plagiarism check before accepting a project submission.

---

### ISSUE-FE-04 · Admin Panel Has No CSP (Content Security Policy) Headers
- **Severity:** Medium
- **File:** [`admin.html`](../Frontend/admin.html)
- **Description:** The admin panel, which displays enrollment codes and allows account deletion, has no `Content-Security-Policy` header. An XSS vulnerability in the admin JS could allow script injection to exfiltrate enrollment codes or trigger admin actions.
- **Action:** Add a strict CSP header via the FastAPI or Cloudflare Pages configuration for the admin page: `default-src 'self'; script-src 'self' <clerk-domain>; ...`

---

### ISSUE-FE-05 · `auth.js` Has Dead `completingEnrollment` Flag (Logic Residue)
- **Severity:** Low / Code Quality
- **File:** [`auth.js`](../Frontend/auth.js)
- **Description:** `let completingEnrollment = false;` is declared at the top of `auth.js` and set to `true` in `showEnrollment()`, but it is never read or checked anywhere else in the file. This is dead code.
- **Action:** Remove the unused variable to reduce confusion during future security audits.

---

## 📋 Section 7 — Deployment & Configuration Issues

### ISSUE-DEP-01 · No HTTPS Enforcement Before Public Deployment
- **Severity:** Critical
- **File:** [`clerk_auth.py`](../clerk_auth.py), [`main.py`](../main.py), [`deployment-config.js`](../Frontend/deployment-config.js)
- **Description:** The application explicitly blocks non-HTTPS origins in production configuration, but deployment has not yet occurred on HTTPS. All login, session tokens, and enrollment codes are transmitted in plaintext if HTTP is used.
- **Status:** **Pre-launch blocker** — explicitly flagged in `Security.md`.

---

### ISSUE-DEP-02 · `TRUSTED_PROXY_IPS` Not Configured — IP Rate Limiting Ineffective
- **Severity:** High
- **File:** [`main.py`](../main.py)
- **Description:** IP-based rate limiting uses `_request_client_ip()`, which only trusts `X-Forwarded-For` from IPs in `TRUSTED_PROXY_IPS`. If this env variable is empty (current state), the backend uses the direct peer IP, which is the proxy's IP — meaning all requests appear to come from the same IP, and IP-level limits are ineffective.
- **Action:** Set `TRUSTED_PROXY_IPS` to the Render/Cloudflare proxy CIDR in production.

---

### ISSUE-DEP-03 · `CLERK_SECRET_KEY` / `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` Must Be Live Keys in Production
- **Severity:** High
- **File:** [`clerk_auth.py`](../clerk_auth.py) (`validate_production_clerk_config`)
- **Description:** The `validate_production_clerk_config()` function enforces that production uses `pk_live_` and `sk_live_` key prefixes. If development keys (`pk_test_`, `sk_test_`) are accidentally deployed to production, startup will crash.
- **Action:** Keep production keys in Render's secret environment store, never in `.env` files committed to git.

---

### ISSUE-DEP-04 · NLTK Resources Must Be Pre-Installed at Build Time
- **Severity:** Medium
- **File:** [`build_backend.sh`](../build_backend.sh), [`plan/release-check-2026-10-07.md`](release-check-2026-10-07.md)
- **Description:** The plagiarism worker requires `stopwords`, `wordnet`, and `omw-1.4` NLTK resources. `build_backend.sh` installs them at build time. If the deployment image is built without running this script, the first plagiarism check will fail.
- **Action:** Verify `build_backend.sh` is part of the Render build command, or add a startup check that validates NLTK resources are available.

---

## 📊 Summary Table

| ID | Area | Severity | Status |
|---|---|---|---|
| ISSUE-AUTH-01 | Clock skew `TOKEN_NOT_ACTIVE_YET` | High | Mitigated (not fixed) |
| ISSUE-AUTH-02 | `/api/config` unauthenticated + no rate limit | Low | Open |
| ISSUE-AUTH-03 | Self-selected identity at registration | **Critical** | **Deployment blocker** |
| ISSUE-AUTH-04 | Portal role mismatch session not cleared | Medium | Open |
| ISSUE-AUTH-05 | Clerk token polling window too short | Medium | Open |
| ISSUE-AUTH-06 | Enrollment code visible in DOM too long | Medium | Open |
| ISSUE-AUTH-07 | `PROJECT_GUARD_API_BASE_URL` is blank | High | **Must fix before deploy** |
| ISSUE-AUTH-08 | Legacy password columns in DB | Medium | Open |
| ISSUE-ACL-01 | No DB uniqueness constraint on `team_members` | High | Open |
| ISSUE-ACL-02 | Admin route enforcement unclear | High | Needs verification |
| ISSUE-ACL-03 | Dead code in `delete_profile_account` | Medium | Open |
| ISSUE-ACL-04 | `is_own` computation on historical messages | Medium | Open |
| ISSUE-ACL-05 | Legacy projects corpus exposure risk | Low | Mitigated |
| ISSUE-CORS-01 | `CORS_ALLOWED_ORIGINS` not set | High | **Must set before deploy** |
| ISSUE-CORS-02 | `CLERK_AUTHORIZED_PARTIES` not set | High | **Must set before deploy** |
| ISSUE-CORS-03 | Dev origins hard-coded as fallback | Low | Open |
| ISSUE-RATE-01 | `/api/config` has no rate limit | Low | Open |
| ISSUE-RATE-02 | `RATE_LIMIT_HASH_KEY` falls back to Clerk key | Medium | Open |
| ISSUE-RATE-03 | Plagiarism semaphore per-process only | Medium | Open |
| ISSUE-DB-01 | Duplicate team memberships in live DB | High | **Needs cleanup before deploy** |
| ISSUE-DB-02 | `MentorStudent.prn` nullable breaks roster | Medium | Open |
| ISSUE-DB-03 | Sessions not used as context managers | Medium | Open |
| ISSUE-DB-04 | Migrations not protected by advisory lock | Low | Open |
| ISSUE-FE-01 | `localStorage` for display (non-sensitive) | Low | Acceptable |
| ISSUE-FE-02 | `alert()` for security messages | Low | Open |
| ISSUE-FE-03 | Plagiarism gate frontend-only | **Medium** | **Open — backend enforcement missing** |
| ISSUE-FE-04 | No CSP on admin panel | Medium | Open |
| ISSUE-FE-05 | Dead `completingEnrollment` flag | Low | Code quality |
| ISSUE-DEP-01 | No HTTPS enforcement at deploy | **Critical** | **Deployment blocker** |
| ISSUE-DEP-02 | `TRUSTED_PROXY_IPS` not set | High | **Must set before deploy** |
| ISSUE-DEP-03 | Clerk live keys not set | High | **Must set before deploy** |
| ISSUE-DEP-04 | NLTK resources not guaranteed at runtime | Medium | Open |

---

## 🚨 Pre-Deployment Blockers (Must Fix Before Going Live)

1. **ISSUE-AUTH-03** — Mentor enrollment entitlement not verified; self-selected identity still possible for mentors.
2. **ISSUE-DEP-01** — HTTPS not set up; all auth tokens transmitted in plaintext over HTTP.
3. **ISSUE-AUTH-07** — `deployment-config.js` has blank API URL; login page will break.
4. **ISSUE-CORS-01 / ISSUE-CORS-02** — `CORS_ALLOWED_ORIGINS` and `CLERK_AUTHORIZED_PARTIES` not configured.
5. **ISSUE-DEP-02** — `TRUSTED_PROXY_IPS` not set; IP rate limiting is broken.
6. **ISSUE-DEP-03** — Production Clerk live keys not deployed.
7. **ISSUE-DB-01** — Duplicate membership rows in live DB need cleanup + `identity_integrity.py --apply`.
8. **ISSUE-FE-03** — Plagiarism bypass: backend must enforce plagiarism threshold at submission.

---

*This report was generated by auditing source files on 2026-10-17. It supplements (and does not replace) the existing `plan/Security.md` and `plan/release-check-2026-10-07.md` documents.*
