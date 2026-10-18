# Enrollment code operations

Use this process before inviting a student or mentor to link a Clerk account to Project Guard.

## Responsibility

The institution's designated enrollment administrator verifies recipients and issues codes. Only that administrator's Clerk user ID, and any formally designated backup administrator, may appear in `ENROLLMENT_ADMIN_CLERK_USER_IDS`. The administrator issuing the code is recorded on the enrollment row. Do not let a recipient verify their own identity or issue their own code.

## Verify the recipient

- **Student:** compare the roll number and academic year with the current official student/registrar roster. Resolve spelling, duplicate, or year discrepancies with the registrar before issuing.
- **Mentor:** confirm the name and staff relationship in the official staff directory or directly through a known institutional contact channel. Do not rely on a name or contact detail supplied only in the request.
- Select the verification method used (`official_roster`, `institutional_contact`, or `in_person`) and affirm the identity check in the admin portal. The database stores the issuing administrator's Clerk ID and method; it does not store copies of identity documents or contact details.
- If authoritative records do not match, stop and refer the request to the registrar or department head. Do not issue a provisional code.

## Deliver and handle the code

- Deliver the code directly to the already verified institutional email/contact or in person. Never post it in a class/team chat, shared document, ticket, or public channel. Do not send it to an address first provided by the requester.
- The code is displayed once in the admin portal, hidden after five minutes, and stored in PostgreSQL only as a hash. Copy it only for immediate private delivery. The recipient enters the code while completing sign-up in the matching student or mentor portal.
- If the code is sent to the wrong person, exposed, or no longer needed, revoke it in the admin portal and issue a new one only after rechecking the recipient. Codes expire and can be used once.
- Keep the existing enrollment audit row. Do not include code values in email, admin notes, screenshots, or support logs.
- If the admin portal is unavailable, an administrator may use `enrollment.py issue` only from a trusted workstation with database access. The command requires an allowlisted verifier ID, verification method, and recipient identity details; deliver its one-time stdout code privately and never save the terminal output.

## Release verification

After the HTTPS frontend and API are deployed and the production Clerk instance is configured, verify in a real browser:

1. A new student can sign up with a valid student code, is linked to the exact roll number/year, lands in the student portal, and remains there after refresh.
2. A new mentor can sign up with a valid mentor code, is linked to the exact mentor record, lands in the mentor portal, and remains there after refresh.
3. A student code cannot link a mentor account; a mentor code cannot link a student account. Wrong identifiers, expired, revoked, and previously used codes are rejected.
4. Signing out clears the active session. Signing in through the other portal does not grant the wrong role; the portal guard and API reject cross-role access.
5. An unallowlisted Clerk account cannot open enrollment administration or issue/revoke codes. The allowlisted administrator can issue, view audit details, and revoke an unused code.
6. Repeat the checks in current Chrome, Safari, and Firefox and confirm redirects, token refresh, and API requests use HTTPS and the deployed origins.

Production browser checks remain pending until hosting and production Clerk settings exist. Use the checklist in `Deploy.md` to configure those origins before testing.
