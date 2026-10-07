# Project visibility and legacy reconciliation

## Decision (2026-10-07)

Preserve historical projects as a restricted archive and plagiarism comparison corpus. Do not delete them or infer ownership from a matching project/team name. The portal treats a project as active only when its `team_id` resolves to an existing team.

- Unlinked legacy rows and rows referencing a missing team are excluded from `/api/projects` and `/mentor/axiom-stream`, including rows with a mentor assignment but no verified team relationship.
- Active unassigned team ideas remain visible to mentors for selection. An explicitly assigned project is visible only to its assigned mentor.
- The project list returns display fields and assignment flags. The abstract is loaded on the server only after Axiom checks the same visibility policy.
- Historical records remain available internally for similarity comparison; the student plagiarism API returns scores and truncation information without matching project identifiers, names, groups, abstracts, or embeddings.
- A legacy team's display name does not reserve that name or prevent a different team from submitting its current idea. New submission does not overwrite the legacy record.
- Mentor-owned roster titles are roster display data. They are not proof that a legacy Project row belongs to that team and cannot unlock its abstract or AI context.

## Response review

| Routes | Caller / data returned |
| --- | --- |
| `GET /api/config` | Public publishable Clerk configuration only. |
| `GET /api/me` | Caller role, application identifier, year. |
| `POST /api/profile/link` | Caller linked role/profile fields; no Clerk subject in the response. Authoritative enrollment remains a separate open issue. |
| `DELETE /api/account` | Caller deletion confirmation and role. |
| `GET /api/projects` | Mentor: canonical team project summary, ID needed for actions, assignment flags. No abstract, embedding, submitter ID, or mentor ID. |
| `POST /mentor/axiom-stream` | Mentor: generated answer about an authorized project. Denies legacy, missing-team, or other-mentor IDs before contacting AI. |
| `PATCH /api/projects/{id}/assign` | Mentor: assignment confirmation and identifiers for the affected project/team. |
| `GET /api/students`, `GET /mentor/students` | Mentor: own roster display/edit fields and permitted team/project titles. No other mentor's assigned project details. |
| `POST /mentor/students/import` | Mentor: aggregate added/updated/removed counts. |
| `POST /mentor/students`, `PUT/DELETE /mentor/students/{id}` | Mentor: own roster mutation confirmation and row ID when created. |
| `GET /mentor/dashboard` | Mentor: own counts and recent review display fields. |
| `POST /mentor/reviews`, `PATCH /mentor/reviews/{id}` | Mentor: own review schedule/status/notes fields needed by the dashboard. |
| `POST /create-team`, `POST /join-team`, `GET /get-student-team` | Student: own team name, join code, member identifiers needed for the roster. |
| `POST /leave-team` | Student: confirmation. |
| `POST /submit-project` | Student: own project ID and submission/assignment confirmation. |
| `POST /team-invitations` | Student: created invitation ID and confirmation. |
| `GET /team-invitations` | Student: own pending invitation ID, team name, inviter. No join code or unused creation timestamp. |
| `PATCH /team-invitations/{id}` | Student: response status; accepted invitations return the student's newly joined team information. |
| `POST /check-plagiarism` | Student: similarity score, risk level, optional input truncation information. |
| `GET /group-connect/groups` | Assigned participant: room reference, display names, member names, shared review schedules/notes. No redundant internal mentor key. |
| `GET/POST /group-connect/messages` | Assigned participant: message display fields and `is_own`. Sender login identifiers/PRNs remain server-side. |
| `GET /chat-stream` | Linked user: generated answer to the submitted prompt; no database project retrieval. |
| Retired signup/login routes | HTTP 410; no account data. |

Group IDs and action IDs are resource references, not authorization. The server still checks the verified profile and group membership for every read/write. Shared review notes are intentionally visible to assigned group participants because the existing group UI renders them; private mentor notes would need a separate field and policy.

## Verified migration workflow

Use `legacy_projects.py` locally with trusted administrator database credentials. No migration endpoint is exposed in the web app. Historical records with no reliable team relationship stay archived; deleting academic history is not needed to secure portal visibility.

1. Inventory legacy rows with `venv/bin/python legacy_projects.py`. Output omits abstracts and vectors.
2. Obtain trusted academic records proving the correct project/team/mentor relationship. Names alone are insufficient. Create a JSON mapping file with exact integer IDs:

   ```json
   [{"project_id": 123, "team_id": 45, "mentor_id": 6}]
   ```

3. Preview: `venv/bin/python legacy_projects.py --mapping verified-project-links.json`. The tool validates the entire batch and rolls back; nothing is persisted.
4. During a maintenance window with roster and portal writes stopped, apply the reviewed mapping: `venv/bin/python legacy_projects.py --mapping verified-project-links.json --apply`. The tool revalidates and commits the batch atomically.

The tool requires existing project/team/mentor rows, an unlinked project, at least two distinct current student members, unambiguous student/membership/roster identities, no competing mentor, and no project already attached to the target team. It preserves the abstract, title, year/group history, and embedding; it sets explicit relationships and synchronizes the assigned mentor's roster titles. It never overwrites an occupied team's project or deletes records. Dangling non-null team IDs require separate administrator repair before this tool can link them.

The tool has not been applied to the application database: administrator-verified mappings have not been supplied.

## Verification

`test_project_visibility.py` exercises portal list and Axiom boundaries, response minimization, name collisions, preview rollback, committed visibility, and rejected migration conflicts. `test_group_connect.py` checks assigned-group reads/writes and chat response minimization. These tests use an isolated SQLite database and test-only verified-profile stubs; they do not validate real Clerk signatures or PostgreSQL transaction/locking behavior. Deployment checks remain separate.
