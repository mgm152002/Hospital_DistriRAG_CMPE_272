export type Classification = "public" | "internal" | "confidential" | "restricted";
export type VersionStatus =
  | "PENDING_APPROVAL" | "REJECTED" | "QUEUED" | "PROCESSING" | "READY" | "SUPERSEDED" | "FAILED";

export interface Persona {
  user_id: string; name: string; role: string; groups: string[]; samples?: string[]; department?: string | null;
}

/** The hospital this deployment serves (HOSPITAL_* settings). */
export interface Hospital { name: string; code: string; campus: string }

export interface Me {
  user_id: string; name: string; role: string; groups: string[]; roles: string[]; samples: string[];
  profile: string; llm_provider: string; llm_external: boolean; llm_model?: string; email?: string; is_demo?: boolean;
  department?: string | null; hospital?: Hospital; member_since?: string;
}

export type ChatProviderId = "local-proxy" | "openrouter-free";
export interface ChatProvider { id: ChatProviderId; label: string; configured: boolean }
export interface ChatModel { id: string; name?: string; context_length?: number }

/** GET/PUT /api/chat/settings. */
export interface ChatSettings {
  provider: ChatProviderId; providers: ChatProvider[]; model: string; models: ChatModel[];
  can_edit: boolean; enabled: boolean; key_configured: boolean; network_access: boolean;
  catalog_notice: string | null; free_only?: boolean; airgapped?: boolean;
  external_max_classification?: Classification; allowed_hosts?: string[];
}

/** GET /api/chat/settings/models?provider=<id>. */
export interface ChatModels { models: ChatModel[]; catalog_notice: string | null }

export interface SearchHit {
  chunk_id: string; document_id: string; version_id: string; title: string; version_number: number;
  category: string; department: string; classification: Classification; section: string | null; page: number;
  score: number; snippet: string; highlights: [number, number][];
}

export interface Passage {
  index: number; chunk_id: string; document_id: string; version_id: string; title: string;
  version_number: number; section: string | null; page: number; classification: Classification;
  category: string; score: number; text: string;
}

export interface Receipt {
  classification: string | null; phi_redacted: boolean; provider: string; model: string; external: boolean;
  egress_decision: string; passages_withheld: Record<string, number>;
  checks: { citations: string; clinical: string; injection: string };
  fallback: string | null; cached: boolean; latency_ms: number; mode?: "extractive";
}

export interface ConversationSummary { conversation_id: string; title: string; updated_at: string; messages: number }
export interface StoredMessage {
  role: "user" | "assistant"; content: string; citations: Passage[] | null; confidence: number | null;
  receipt: Receipt | null; created_at: string;
}

export interface DemoGroup {
  scenario: string; title: string; description: string; conversations: { id: string; turns: string[] }[];
}
export interface DemoQuestions { enabled: boolean; groups: DemoGroup[] }

export interface PhiNotice { types: string[]; notice?: string }
export interface Preview { index: number; title: string; version_number: number; section: string | null; text: string }

export interface CitedPassage extends Passage { cited?: boolean }

export interface ChatFinal {
  answer: string; citations: Passage[]; cited: number[]; confidence: number; band: "High" | "Medium" | "Low";
  parts: { r: number; c: number; a: number }; receipt: Receipt; fallback: string | null; conversation_id: string;
  note?: string | null;
}

export interface DocumentRow {
  document_id: string; title: string; category: string; department: string; classification: Classification;
  owner_id: string; created_at: string; retired_at: string | null; active_version_number: number | null;
  latest_version_id: string; latest_version_number: number; latest_status: VersionStatus; latest_stage: string | null;
  chunks_total: number; chunks_embedded: number; updated_at: string; error_code: string | null; groups: string[];
}

export interface VersionInfo {
  version_id: string; version_number: number; status: VersionStatus; stage: string | null; chunks_total: number;
  chunks_embedded: number; uploaded_by: string; approved_by: string | null; approved_at: string | null;
  effective_date: string | null; review_due: string | null; error_code: string | null; error: string | null;
  created_at: string; filename: string;
}

export interface DocumentDetail {
  document_id: string; title: string; category: string; department: string; classification: Classification;
  owner_id: string; active_version_id: string | null; retired_at: string | null; created_at: string;
  groups: string[]; versions: VersionInfo[];
}

export interface Chunk { chunk_id: string; chunk_index: number; page: number; section: string | null; text: string }

export interface VersionText {
  document: { document_id: string; title: string; category: string; classification: Classification;
              active_version_id: string | null };
  version: VersionInfo; chunks: Chunk[];
}

export interface BoardCard {
  version_id: string; document_id: string; title: string; version_number: number; status: VersionStatus;
  stage: string | null; chunks_total: number; chunks_embedded: number; error_code: string | null; updated_at: string;
}

export interface OpsEvent { id: number; kind: string; version_id: string | null; detail: Record<string, unknown>;
                            created_at?: string }

export interface StreamStat {
  stream: string; group: string; length: number; pending: number; lag: number; dlq: number;
  consumers: { name: string; pending: number; idle_ms: number }[];
}

export interface AuditEntry { audit_id: number; actor_id: string; action: string; target: string | null;
                              detail: Record<string, unknown>; created_at: string }
