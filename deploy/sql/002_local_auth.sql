CREATE TABLE user_accounts (
    user_id text PRIMARY KEY,
    email text NOT NULL UNIQUE,
    display_name text NOT NULL,
    role_name text NOT NULL DEFAULT 'Staff member',
    groups text[] NOT NULL DEFAULT ARRAY['all-staff']::text[],
    password_hash text NOT NULL,
    is_demo boolean NOT NULL DEFAULT false,
    disabled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE auth_sessions (
    token_hash text PRIMARY KEY,
    user_id text NOT NULL REFERENCES user_accounts ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX auth_sessions_expiry ON auth_sessions(expires_at);
CREATE TABLE auth_attempts (
    id bigserial PRIMARY KEY,
    identifier_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_attempts_recent ON auth_attempts(identifier_hash, created_at);
