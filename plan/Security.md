# Project Guard Security Issues and Priorities

This is a code-based security priority list for work to complete before public deployment. It is not a full security audit or a guarantee that it covers every issue.

## Priority order

- [ ] **Require verified identity and ownership checks**
   - [x] Integrate Clerk authentication and verify Clerk session tokens in FastAPI.
   - [x] Take the authenticated Clerk user ID from the verified identity, not from request fields such as `roll_no` or `mentor_user`.
   - [x] Link Clerk users to the corresponding student or mentor record in PostgreSQL. Safe enrollment of new identities against an authoritative student roster remains unresolved.
   - [ ] Check permissions and ownership for every student, team, project, and mentor record touched by a request. Current routes have been reviewed and targeted access-control tests pass; untrusted self-registration against an arbitrary student identifier still prevents completing this item.
   - [x] Require authentication for every API route that returns or changes application data.

- [ ] **Lock down endpoints and validate input**
   - [x] Keep data-returning endpoints private; no API route that exposes application data should remain public.
   - [x] Review current route responses to return fields needed by the authorized caller. Legacy or orphaned project rows are excluded from portal lists and Axiom; they remain a restricted historical comparison corpus. See `plan/project-visibility.md` for the route response review and verified migration workflow.
   - [x] Bound and validate active API request inputs. Legacy password registration/login routes are retired.
   - [x] Add shared account and IP limits for authentication and costly endpoints, backed by PostgreSQL so limits apply across API workers. Configure trusted proxy IP ranges at deployment when the host sits behind a proxy.

- [ ] **Replace permissive CORS**
   - [x] The backend now requires an explicit origin allowlist in production and rejects wildcards or paths.
   - [ ] Configure every independently deployed frontend origin controlled by the project in the backend environment.
   - [x] Treat CORS as a browser policy, not as API authorization; it does not replace Clerk token verification or access checks.

- [ ] **Protect uploaded documents and expensive operations**
   - [x] Keep upload size and file type limits.
   - [x] Add shared request rate limits and timeouts for uploads and AI endpoints. Plagiarism checks run in a separate process with a hard deadline, and the concurrency queue is bounded.
   - [x] Bound major input sizes and review resource consumption for plagiarism documents, roster imports, embeddings, and chatbot requests. Revisit limits against production data volume.

- [ ] **Harden deployment and secrets**
   - Use HTTPS for deployed frontend and API traffic.
   - Keep Clerk secret keys, database credentials, and AI provider secrets in backend/deployment secret storage.
   - Restrict database access to the application and trusted administrators.
   - Avoid logging passwords, session tokens, Clerk tokens, or sensitive student data.

- [ ] **Review browser storage and XSS risks**
   - [x] Replace `localStorage` identity checks with Clerk session state; never treat a browser-stored username or roll number as authentication.
   - [x] Do not put long-lived authentication tokens in browser storage without a deliberate session design.
   - [x] Review frontend rendering and inputs for cross-site scripting risks, since JavaScript-accessible storage can be exposed by an XSS flaw.
   - [x] Keep `localStorage` only for non-sensitive presentation preferences where appropriate.

## Work completed (2026-10-06)

- Removed caller-supplied identity fields from team, invitation, mentor roster/review, project submission, and group-chat requests where the backend already derives identity from the verified Clerk profile.
- Added bounded request validation for project, team, invitation, mentor roster/review, chat, and plagiarism inputs; unexpected JSON fields are rejected on those request models.
- Scoped mentor student and project list responses to the authenticated mentor's roster assignments.
- Disabled self-service transfer of a PRN already assigned to another mentor; administrator intervention is required for reassignment.
- Production CORS already requires exact HTTPS origins. Each deployed frontend origin still needs to be added to the backend environment allowlist.
- Added PostgreSQL-backed fixed-window quotas for Clerk accounts and client IPs, shared across API workers. Forwarded client IPs are trusted only from configured proxy networks (`TRUSTED_PROXY_IPS`); configure this only with the host's documented proxy ranges.
- Added a bounded plagiarism concurrency queue and run CPU-bound checks in a child process that is killed at the 90-second deadline. Groq has a 45-second timeout with retries disabled; Cloudflare embedding requests have a 30-second timeout.
- Replaced raw database exception responses and detailed exception logging with generic client errors and exception-type-only logs.
- Escaped project/member data in dynamic HTML and replaced profile-avatar HTML interpolation with safe DOM construction and image type/size checks.
- New student profile creation still accepts a self-selected roll number when no student row exists. Per the current deployment discussion, authoritative enrollment proof is deferred; revisit before public launch.

## Team and project data workflow

- A team is identified by its PostgreSQL team ID. Its members are stored as team membership rows; display names and team names are not ownership keys.
- Roster uploads replace the uploading mentor's current roster rows after the full sheet validates; rows missing from that sheet are removed. Reject duplicate PRNs and PRNs owned by another mentor.
- A student can submit a project idea only when the team has at least two members. PostgreSQL keeps one current project row per team.
- Resubmitting an idea overwrites that team's student-owned project fields (title, abstract, year/group display data, and embedding). It does not change team membership or the mentor assignment.
- Mentors see the project list. New unassigned team ideas are available to mentors; assigned projects are visible to their assigned mentor. A mentor's “Assign to me” action assigns the authenticated mentor to the project and its team members.
- A project can have only one mentor assignment. Assignment is rejected when the team's roster already places a member under a different mentor; use an administrative roster correction before assigning in that case.
- Roster re-import overwrites the uploading mentor's own student roster fields. It cannot take a student row from a different mentor, and it cannot overwrite the canonical project title submitted by the student team.
- Historical projects without a valid team relationship are preserved in PostgreSQL for internal plagiarism comparison and excluded from portal project lists and Axiom, even if they have a mentor assignment. Use `legacy_projects.py` with explicit administrator-verified project/team/mentor IDs to preview and apply a migration; otherwise retain the restricted archive. Names alone are not ownership proof.

## Ownership audit (2026-10-07)

- Every registered application-data route, including the `/group-connect` router, passes through the default Clerk middleware. `/api/config` exposes browser-safe configuration only; OPTIONS and documentation routes are infrastructure exceptions. Role-specific handlers additionally check student or mentor role where required.
- Student team, project-submission, and invitation actions derive the acting student's identifier from the linked Clerk profile. Invitation reads and responses are scoped to the authenticated invitee; invitation creation requires the authenticated inviter to be a current team member.
- Mentor roster and review mutations are scoped to the authenticated mentor key. Project assignment is scoped to the authenticated mentor and refuses projects already assigned to someone else. Project data for a student's team is now hidden from another mentor's roster/dashboard responses when explicitly assigned to a different mentor.
- Axiom now accepts a project ID and loads authorized project content from PostgreSQL instead of trusting project title, abstract, group, or year supplied by the browser. Student plagiarism responses omit matched project/team records and return only the score/risk summary.
- Team create/join/leave and invitation accept now lock the authenticated student row; team membership/capacity writes lock the team row. This serializes the relevant writes on PostgreSQL, but existing duplicate or case-variant membership rows still need data cleanup and a database-level uniqueness constraint before this can be considered fully enforced.
- **Blocking ownership gap:** `/api/profile/link` still permits a new Clerk identity to create a student or mentor profile using a self-selected identifier when no profile row exists. Clerk proves the caller controls that Clerk account; it does not prove the caller owns that roll number or mentor identity. Until profile creation is tied to an authoritative enrollment/mentor source or a trusted administrative linking process, an attacker can claim a fabricated student identity. This is distinct from invitation delivery and remains open.
- **Project visibility policy:** only projects with an existing team relationship appear in the mentor portal. Unassigned team ideas remain available for mentor selection; assigned projects are scoped to their assigned mentor. Stale roster links that conflict with that mentor assignment are also excluded from roster, dashboard, and group-chat access.

## Project visibility and response review completed (2026-10-07)

- Centralized project list/Axiom access checks in `project_access.py`; legacy and missing-team rows are hidden from both paths.
- Chose retention with restricted access rather than deletion, preserving the plagiarism corpus. Added an administrator-only migration tool with rollback previews, whole-batch validation, and explicit apply. No mapping has been applied to the application database.
- Removed project abstracts/team database IDs from list responses, unused Clerk subject fields from profile-link responses, join codes/timestamps from pending invitation lists, redundant mentor keys from room responses, and sender login identifiers from message responses. Chat uses server-computed `is_own`; updated frontend asset versions prevent stale scripts using the old response shape.
- Documented the current routes and their response purpose in `plan/project-visibility.md`. Shared group review notes remain intentionally visible to assigned participants because the group UI displays them.
- Fifteen focused tests pass for visibility, AI context authorization, response privacy, stale roster/group access, name collisions, and migration preview/commit/conflict behavior. They use an isolated SQLite database and trusted-profile stubs; real Clerk signature validation and PostgreSQL locking still require deployment verification.

## Deployment prerequisite

- Keep deployment blocked until the frontend and API use HTTPS. The application currently requires HTTPS production origins in its CORS/Clerk configuration; set the actual hosting URLs and proxy ranges when the hosting setup is ready.

## Verification goals

The current route response review was completed on 2026-10-07 with the targeted tests described above. These deployment verification goals remain unchecked until exercised with real Clerk sessions and PostgreSQL against a running deployment.

After implementing these changes, verify that:

- [ ] Unauthenticated requests to protected data routes fail.
- [ ] Invalid or expired Clerk tokens fail verification.
- [ ] One student or mentor cannot access another user's records or perform actions outside their role.
- [ ] Caller-supplied roll numbers, mentor usernames, and roles cannot bypass authorization.
- [ ] CORS accepts only the configured frontend origins.
- [ ] Upload limits, timeouts, and abuse protections apply to document and AI endpoints.

This list reflects observed project risks and planned safeguards. A complete security review may identify additional issues.
# Student enrollment implementation (October 7)

New student profile linking now requires a single-use enrollment code issued using the private `enrollment.py` backend command. The grant binds roll number and year to the verified Clerk session, expires, can be revoked, and is consumed transactionally. See `student-enrollment.md` for usage. Existing linked students are retained. Mentor enrollment entitlement and production flow verification remain pending; this does not clear the overall public deployment blocker.
