# Authentication and administration implementation plan

Goal: add email/password login, registration and demo accounts, with a unified admin panel for analytics,
document intake, independent approval/rejection, and version history/comparison.

Architecture: retain FastAPI, React and Postgres. Add local auth alongside header/OIDC modes. Passwords use salted
scrypt; opaque sessions use HttpOnly same-site cookies and hashed server tokens. Registration grants all-staff only.
Existing document services remain authoritative; the admin panel uses their upload/approval/version endpoints.

- [x] Auth migration, password functions and session services, tests for registration/login/logout/access isolation.
- [x] Public auth bootstrap and demo cards; cookie-aware frontend session, login/registration forms.
- [x] Admin analytics API and dashboard, with counts/trends/category distribution and metadata-only activity.
- [x] Unified documents and approvals pages; version history and text comparison using existing lifecycle services.
- [x] Unit/integration/frontend/browser verification; enable local auth, seed demo accounts and rebuild on port 8080.

Review focus: no self-granted roles, no header impersonation in local mode, expiring/revocable sessions, login abuse
limits, no source text in analytics, no self-approval, and v1 remaining active while v2 awaits approval/indexing.
