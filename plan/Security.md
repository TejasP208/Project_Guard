# Project Guard Security Issues and Priorities

This is a code-based security priority list for work to complete before public deployment. It is not a full security audit or a guarantee that it covers every issue.

## Priority order

- [ ] **Require verified identity and ownership checks**
   - Integrate Clerk authentication and verify Clerk session tokens in FastAPI.
   - Take the authenticated Clerk user ID from the verified identity, not from request fields such as `roll_no` or `mentor_user`.
   - Link Clerk users to the corresponding student or mentor record in PostgreSQL.
   - Check permissions and ownership for every student, team, project, and mentor record touched by a request.
   - Require authentication for every API route that returns or changes application data.

- [ ] **Lock down endpoints and validate input**
   - Keep data-returning endpoints private; no API route that exposes application data should remain public.
   - Review each route to ensure it returns only fields the authorized caller needs.
   - Validate registration, login, and all other request inputs.
   - Add abuse protection to authentication flows and any other externally reachable endpoints.

- [ ] **Replace permissive CORS**
   - The current backend allows any origin.
   - Once deployment domains are chosen, allow only frontend origins controlled by the project.
   - Treat CORS as a browser policy, not as API authorization; it does not replace Clerk token verification or access checks.

- [ ] **Protect uploaded documents and expensive operations**
   - Keep upload size and file type limits.
   - Add request rate limits and timeouts for uploads and AI endpoints.
   - Consider resource consumption and abuse risks for plagiarism checks, embeddings, and chatbot requests.

- [ ] **Harden deployment and secrets**
   - Use HTTPS for deployed frontend and API traffic.
   - Keep Clerk secret keys, database credentials, and AI provider secrets in backend/deployment secret storage.
   - Restrict database access to the application and trusted administrators.
   - Avoid logging passwords, session tokens, Clerk tokens, or sensitive student data.

- [ ] **Review browser storage and XSS risks**
   - Replace `localStorage` identity checks with Clerk session state; never treat a browser-stored username or roll number as authentication.
   - Do not put long-lived authentication tokens in browser storage without a deliberate session design.
   - Review frontend rendering and inputs for cross-site scripting risks, since JavaScript-accessible storage can be exposed by an XSS flaw.
   - Keep `localStorage` only for non-sensitive presentation preferences where appropriate.

## Verification goals

After implementing these changes, verify that:

- [ ] Unauthenticated requests to protected data routes fail.
- [ ] Invalid or expired Clerk tokens fail verification.
- [ ] One student or mentor cannot access another user's records or perform actions outside their role.
- [ ] Caller-supplied roll numbers, mentor usernames, and roles cannot bypass authorization.
- [ ] CORS accepts only the configured frontend origins.
- [ ] Upload limits, timeouts, and abuse protections apply to document and AI endpoints.

This list reflects observed project risks and planned safeguards. A complete security review may identify additional issues.
