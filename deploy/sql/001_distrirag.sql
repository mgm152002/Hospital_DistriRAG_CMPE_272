-- DistriRAG schema (spec 7.2). PostgreSQL is the source of truth; Redis only carries work.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    document_id       uuid PRIMARY KEY,
    title             text NOT NULL,
    category          text NOT NULL,
    department        text NOT NULL,
    classification    text NOT NULL CHECK (classification IN ('public','internal','confidential','restricted')),
    owner_id          text NOT NULL,
    active_version_id uuid,
    retired_at        timestamptz,
    deleted_at        timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_acl (
    document_id uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
    group_name  text NOT NULL,
    PRIMARY KEY (document_id, group_name)
);

CREATE TABLE document_versions (
    version_id      uuid PRIMARY KEY,
    document_id     uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
    version_number  int  NOT NULL,
    status          text NOT NULL,
    stage           text,
    chunks_total    int  NOT NULL DEFAULT 0,
    chunks_embedded int  NOT NULL DEFAULT 0,
    object_key      text NOT NULL,
    filename        text NOT NULL DEFAULT '',
    text_key        text,
    content_type    text NOT NULL,
    content_sha256  text NOT NULL,
    effective_date  date,
    review_due      date,
    uploaded_by     text NOT NULL,
    approved_by     text,
    approved_at     timestamptz,
    error_code      text,
    error           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, version_number),
    CHECK (approved_by IS NULL OR approved_by <> uploaded_by)
);
CREATE INDEX document_versions_status_idx ON document_versions (status, updated_at);

ALTER TABLE documents ADD CONSTRAINT documents_active_version_fk
    FOREIGN KEY (active_version_id) REFERENCES document_versions (version_id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE document_chunks (
    chunk_id    uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
    version_id  uuid NOT NULL REFERENCES document_versions ON DELETE CASCADE,
    chunk_index int  NOT NULL,
    page_number int  NOT NULL,
    section     text,
    text        text NOT NULL,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(section, '') || ' ' || text)) STORED,
    UNIQUE (version_id, chunk_index)
);
CREATE INDEX document_chunks_document_idx ON document_chunks (document_id);
CREATE INDEX document_chunks_tsv_idx ON document_chunks USING gin (tsv);

CREATE TABLE document_embeddings (
    chunk_id  uuid PRIMARY KEY REFERENCES document_chunks ON DELETE CASCADE,
    embedding vector(384) NOT NULL
);
CREATE INDEX document_embeddings_hnsw_idx ON document_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE outbox (
    id           bigserial PRIMARY KEY,
    stream       text NOT NULL,
    event_type   text NOT NULL,
    dedupe_key   text NOT NULL UNIQUE,
    payload      jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    attempts     int NOT NULL DEFAULT 0,
    last_error   text
);
CREATE INDEX outbox_unpublished_idx ON outbox (id) WHERE published_at IS NULL;

CREATE FUNCTION outbox_notify() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN PERFORM pg_notify('outbox', NEW.id::text); RETURN NEW; END $$;
CREATE TRIGGER outbox_notify_trg AFTER INSERT ON outbox FOR EACH ROW EXECUTE FUNCTION outbox_notify();

CREATE TABLE embed_batches (
    version_id uuid NOT NULL REFERENCES document_versions ON DELETE CASCADE,
    batch_no   int  NOT NULL,
    chunk_from int  NOT NULL,
    chunk_to   int  NOT NULL,
    done_at    timestamptz,
    PRIMARY KEY (version_id, batch_no)
);

CREATE TABLE idempotency_keys (
    key         text PRIMARY KEY,
    user_id     text NOT NULL,
    request_sha text NOT NULL,
    response    jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE dead_letters (
    id          bigserial PRIMARY KEY,
    stream      text NOT NULL,
    message_id  text NOT NULL,
    payload     jsonb NOT NULL,
    deliveries  int NOT NULL,
    error       text,
    replays     int NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    replayed_at timestamptz
);

CREATE TABLE conversations (
    conversation_id uuid PRIMARY KEY,
    user_id         text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL
);
CREATE TABLE messages (
    message_id       uuid PRIMARY KEY,
    conversation_id  uuid NOT NULL REFERENCES conversations ON DELETE CASCADE,
    role             text NOT NULL,
    content_redacted text NOT NULL,
    citations        jsonb,
    confidence       int,
    receipt          jsonb,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE answer_cache (
    key          text PRIMARY KEY,
    answer       jsonb NOT NULL,
    document_ids uuid[] NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ops_events (
    id         bigserial PRIMARY KEY,
    kind       text NOT NULL,
    version_id uuid,
    detail     jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
    audit_id   bigserial PRIMARY KEY,
    actor_id   text NOT NULL,
    action     text NOT NULL,
    target     text,
    detail     jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_created_idx ON audit_log (created_at);

-- Append-only audit (CP-5): only the retention job, which sets distrirag.allow_audit_purge, may delete.
CREATE FUNCTION audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_setting('distrirag.allow_audit_purge', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'audit_log is append-only';
END $$;
CREATE TRIGGER audit_append_only_trg BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_append_only();
