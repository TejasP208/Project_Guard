# Student enrollment codes

Implemented student enrollment using codes issued from the private backend terminal. Clerk still authenticates the account. A valid code authorizes linking that Clerk user to the specified student roll number and year.

## Issue a code

From the project directory with the private backend `DATABASE_URL` configured:

```sh
venv/bin/python enrollment.py issue --roll-no "YOUR-STUDENT-ROLL" --year "YOUR-YEAR" --expires-hours 168
```

The command creates the enrollment table if needed, then prints the enrollment ID and a random code once. Send the code privately through your chosen channel. The command does not send messages. Terminal access and database credentials authorize the operator. Codes expire in seven days by default. Avoid shared terminal logs when issuing codes.

## Admin page

Set `ENROLLMENT_ADMIN_CLERK_USER_IDS` in the private backend environment to the exact Clerk user IDs of trusted administrators (comma-separated). Get these IDs from the Clerk dashboard; never use a roll number, username, or frontend-selected role. Restart FastAPI after updating the environment. An empty allowlist denies all admin access.

Open `/admin.html` on the frontend server and sign in with that Clerk account. The page issues codes, displays each new code once, lists the latest 200 grants, and revokes available codes. Admin endpoints verify Clerk sessions and the backend allowlist; an academic student/mentor profile is not required for an administrator. Existing terminal commands remain available. No real administrator ID has been configured by this change.

After an enrollment error, password fields remain visible. Leave both blank to keep the existing Clerk password, or enter a matching new password. Changing an existing password uses Clerk's password update flow and requires the current password (the initial signup password is available in memory during the same signup attempt). Passwords are never sent to PostgreSQL or the enrollment API. Reloading clears that in-memory value.

The year must match exactly after trimming spaces; roll number comparison ignores case and outer spaces. Use the same year convention as the student portal.

## Revoke a code

```sh
venv/bin/python enrollment.py revoke --id 123
```

Revoke an earlier code before issuing a replacement. Revocation does not unlink a profile already enrolled.

## Student flow

Student signup collects roll number, year, enrollment code, and Clerk credentials. FastAPI verifies the Clerk session; new student profiles require a matching, unused, unexpired, unrevoked code. It saves identity fields from the grant, never trusts a caller-supplied Clerk user ID, and uses one transaction for redemption and linking. Existing unlinked student records can be linked by a valid grant; already linked or ambiguous identities are rejected. Existing linked students retain access and cannot change their year through profile linking.

After an unsuccessful enrollment, the Clerk account may already exist. Sign in to that account and complete enrollment on the displayed form. Do not create a second account. Existing endpoint rate limiting applies to redemption. PostgreSQL advisory locks serialize student claims by Clerk subject and normalized roll number; the grant row is also locked to prevent reuse.

## Remaining work

- Mentor self-enrollment remains unchanged and is still a public deployment blocker. This student implementation does not authorize mentor accounts.
- Resolve old duplicate team memberships and apply the identity integrity migration.
- Verify code issuance/redemption/concurrent attempts and real Clerk browser flows before deployment. No live grants have been issued as part of this implementation, and no enrollment has been redeemed.
- Production origins, live keys, and hosting remain pending.
