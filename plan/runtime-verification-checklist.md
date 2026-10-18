# Deployed runtime verification checklist

**Status (2026-10-18): BLOCKED — no staging or production hosting has been created.** The checks below require a deployed HTTPS frontend and API, the intended PostgreSQL/pgvector service, private provider credentials, and dedicated test accounts. No production browser, provider, or PostgreSQL multi-worker flow is claimed as tested here.

Use a staging deployment with synthetic student/mentor accounts and disposable teams/projects. Do not use real student submissions or production identities. Record evidence without bearer tokens, enrollment codes, provider keys, or private student data.

## Record the run

| Field | Value |
|---|---|
| Run date / operator | Pending |
| Commit SHA | Pending |
| Frontend HTTPS origin | Pending |
| API HTTPS origin | Pending |
| Backend worker count / instance type | Pending |
| PostgreSQL provider and version | Pending |
| Clerk instance (test/live) | Pending |
| Result | Not run — hosting unavailable |

## Preconditions

- [ ] Frontend and API use HTTPS; frontend API base URL points to the deployed API.
- [ ] `APP_ENV=production`; Clerk authorized parties and CORS contain the exact frontend origin; trusted proxy CIDRs come from the hosting provider.
- [ ] API connects to the intended PostgreSQL database with pgvector and indexed project embeddings.
- [ ] At least two backend workers are running for cross-worker checks.
- [ ] Two student test accounts on different teams, one mentor account, and one unlinked or wrong-role account are available. Their profiles are synthetic and can be removed after the run.
- [ ] Groq and Cloudflare credentials are configured in the provider's secret manager.
- [ ] A valid small TXT, PDF, and DOCX test document, a malformed document, and an oversized upload are ready.
- [ ] Request IDs and status codes can be recorded without logging authorization headers or request bodies containing personal data.

## Checks

| ID | Check and procedure | Pass condition | Result / evidence |
|---|---|---|---|
| RT-01 | Open the frontend directly and follow sign-up, sign-in, redirect to the student portal, refresh, sign-out, and sign-in again in Chrome, Safari, and Firefox. Repeat for the mentor portal. | Correct portal after each redirect; session survives refresh; sign-out clears access; no token-missing loops or console errors. | Pending |
| RT-02 | In a staging-only browser session, test an expired session, missing session, tampered token, and a session whose authorized party is not the frontend origin. | API rejects each unauthenticated/invalid request with 401; browser returns to the expected sign-in flow without exposing protected data. | Pending |
| RT-03 | Use the student account against mentor-only actions, then alter project/team identifiers to reference another student's or mentor's records. Try read and write routes. | Role violations are rejected; cross-account reads/writes return the documented denial/not-found status and reveal no protected record details. | Pending |
| RT-04 | Send CORS preflight and ordinary API requests from the exact configured frontend origin, a second unconfigured HTTPS origin, and a non-browser client. | Exact origin receives the expected allow headers; unconfigured origin receives no allow-origin header; non-browser requests still require valid Clerk authorization. | Pending |
| RT-05 | Through the real hosting proxy, make requests with and without `X-Forwarded-For`; then attempt a forged forwarded address from an untrusted peer if the staging topology permits. Inspect rate-limit attribution without recording real user IPs. | Only requests from configured trusted proxy ranges influence forwarded client IP; direct/spoofed headers cannot bypass IP limits. | Pending |
| RT-06 | From two workers/accounts, issue simultaneous invitations/accepts or other same-team membership writes, including a capacity-boundary race. Inspect the committed PostgreSQL rows afterward. | No duplicate student membership, over-capacity team, partial invite, lost update, or inconsistent cleanup; constraints and row locks behave across workers. | Pending |
| RT-07 | Submit several `/check-plagiarism` requests concurrently so they land on different workers. Repeat once while the PostgreSQL advisory lock is held by a staging-only test session, then release it. | At most the configured check concurrency proceeds; excess requests return the documented 429/Retry-After; no worker hangs; the lock is released after success, timeout, and error. | Pending |
| RT-08 | Upload each valid document type through `/check-plagiarism`; then test malformed, unsupported, empty/scanned, and over-limit files. Check student response fields. | Valid files return a finite score; invalid/oversized files receive the documented 4xx; student responses omit matched project/team details; truncation is disclosed. | Pending |
| RT-09 | Submit a team project after a successful score check and also call `/submit-project` directly without relying on the prior browser check. If `ORIGINALITY_BLOCK_THRESHOLD` is unset, verify the score is advisory; if configured, test just below, equal to, and just above it. | Server rechecks the exact title/abstract; submission behavior matches the backend threshold setting; invalid checker output fails closed; no browser-only control is relied upon. | Pending |
| RT-10 | Exercise the mentor AI stream with a valid assigned project; then test an unassigned project ID and a provider timeout/error in staging. | Assigned project streams successfully; unauthorized project is denied; provider failure is bounded and returns a safe error without leaking credentials or stack traces. | Pending |
| RT-11 | Run one real Cloudflare embedding-backed comparison and one Groq stream using staging data; inspect service logs for failures and accidental secrets. | Both providers respond through the deployed backend; database vector search returns expected-shaped results; secrets and bearer tokens are absent from logs. | Pending |
| RT-12 | Restart one backend worker during idle traffic, then during a controlled plagiarism check if safe. Verify database connection recovery and retry behavior. | Service recovers without persistent lock/semaphore blockage or duplicate project writes; transient errors are surfaced safely. | Pending |

For every failed check, record the request ID, UTC time, route, status, worker/instance, and sanitized error summary. File a follow-up against the failing check before marking this release gate complete.

## Completion gate

Do not mark runtime verification complete until every applicable row is Pass, failures have been fixed and rerun, and the evidence is reviewed. If a provider capability or browser is unavailable, record it as Not run with the reason; do not treat it as a pass. Re-run this checklist after auth, hosting, database, proxy, or provider configuration changes.
