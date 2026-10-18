# Clerk token timing incident

The reported login response `TOKEN_NOT_ACTIVE_YET` comes from the API's Clerk token verification. The session token's `nbf` time was later than the API verifier accepted. The login page previously signed out on every `/api/me` 401, which could then leave the portal with no Clerk session and display its generic “Portal unavailable” panel. The screenshots do not establish which clock was wrong or whether a separate domain issue also exists.

## Deployment checks

1. On the failing deployment, compare the API host's UTC time with a trusted time source. Check host time synchronization before changing verification tolerance.
2. In browser developer tools, record the `/api/me` HTTP status and response detail. For one failing session, compare token `iat`, `nbf`, and `exp` with the API host time. Decode claims locally; do not paste, log, or send the bearer token.
3. Confirm login and dashboard use the same exact origin. If they use different domains, set up Clerk's documented primary/satellite configuration and redirect flow. Confirm the frontend origin also appears in backend `CLERK_AUTHORIZED_PARTIES` and `CORS_ALLOWED_ORIGINS`.
4. After correcting the clock or domain configuration, test a fresh student and mentor login, direct portal load, refresh, and sign-out on the deployed origin.

The frontend now retries only `TOKEN_NOT_ACTIVE_YET` for at most seven seconds and preserves the session if it persists. This limits the symptom but cannot correct a server clock that remains out of sync.
