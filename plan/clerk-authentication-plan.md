# Project Guard Clerk Authentication Plan

## Goal

Use Clerk for student and mentor sign-up, sign-in, and session management through one Clerk application. Keep the student and mentor portals visually separate, and continue using PostgreSQL for application data such as student records, teams, projects, and mentor rosters.

Every API route that returns or changes application data must require authentication. FastAPI will verify Clerk session tokens and use the verified Clerk user ID to identify and authorize the caller. Values supplied by the browser, such as a roll number, mentor username, or role, are not proof of identity or authorization.

## Implementation plan

- [ ] **Connect the app to Clerk**
   - Use the Clerk application and keys already configured in `.env`.
   - Use the publishable key in the frontend.
   - Keep the Clerk secret key on the backend only; never expose or commit it.

- [ ] **Replace the current authentication flows**
   - Integrate Clerk's JavaScript SDK for sign-up, sign-in, and sign-out.
   - Use the same Clerk application for students and mentors.
   - Preserve the separate student and mentor portal interfaces.

- [ ] **Link Clerk identities to PostgreSQL records**
   - Add a stable Clerk user ID to student and mentor records.
   - Keep application profile fields—such as roll number, year, and mentor name—in PostgreSQL.

- [ ] **Manually link existing test accounts**
   - Manually associate each existing test account with its matching Clerk user.
   - Keep the current test data during development; do not migrate or recreate it as part of authentication setup.

- [ ] **Verify Clerk sessions in FastAPI**
   - Require a valid Clerk session token on protected API requests.
   - Verify its signature and claims on the backend.
   - Resolve the authenticated user from the verified Clerk user ID and the linked application record.

- [ ] **Protect the API**
   - Require authentication for all routes that return or change application data, including student, mentor, team, project, and roster routes.
   - Review utility endpoints and explicitly decide whether each requires sign-in.
   - Do not trust caller-supplied roll numbers, mentor usernames, or roles to establish identity or grant access.

- [ ] **Update frontend session handling**
   - Replace `localStorage`-based login checks with Clerk session state.
   - Send the Clerk session token with API requests.
   - Sign out through Clerk.
   - Keep browser-stored profile preferences only when they are used for display, not authorization.

- [ ] **Configure and verify deployment**
   - Configure production Clerk keys and allowed URLs in the deployment environment.
   - Keep the secret key private on the backend.
   - Verify sign-in, sign-out, and protected API access over HTTPS.

- [ ] **Add admin-controlled mentor approval last**
   - Keep the current website mentor sign-up flow during the main authentication work.
   - As the final implementation step, add an admin portal or another admin-controlled process for approving mentors or managing mentor account creation.

- [ ] **Remove test data before real data is added**
    - Before allocating real student and project data, delete the fake test accounts and their related test data.
    - Create a separate file documenting the test-data cleanup process when the project reaches that stage.

## Agreed decisions

- Students and mentors use one Clerk application, with separate portal UIs.
- Existing test accounts will be linked manually to Clerk users.
- Fake accounts and test data remain during development and will be deleted before real data is allocated.
- Mentor approval/admin controls are the final implementation step.
- No API route that exposes application data will remain public.
