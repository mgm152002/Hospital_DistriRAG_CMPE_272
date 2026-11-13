import type { DocumentDetail, Me, Persona, SearchHit, VersionText } from "../api/types";

export const personas: Persona[] = [
  { user_id: "priya", name: "Dr. Priya Rao", role: "Attending physician", groups: ["all-staff", "clinical", "physicians"] },
  { user_id: "sam", name: "Sam Lee", role: "Registered nurse", groups: ["all-staff", "clinical", "nursing"] },
  { user_id: "jordan", name: "Jordan Kim", role: "Clinical pharmacist", groups: ["all-staff", "clinical", "pharmacy"] },
  { user_id: "riley", name: "Riley Chen", role: "Patient services / front desk", groups: ["all-staff"] },
  { user_id: "alex", name: "Alex Morgan", role: "Knowledge administrator", groups: ["all-staff", "doc-admins"] },
  { user_id: "taylor", name: "Taylor Brooks", role: "Compliance officer", groups: ["all-staff", "compliance"] },
  { user_id: "casey", name: "Casey Diaz", role: "Platform operator", groups: ["operators"] },
];

export const hospital = { name: "Riverside General Hospital", code: "RGH-001", campus: "Main campus" };

export function me(userId: string): Me {
  const p = personas.find((x) => x.user_id === userId)!;
  return { ...p, roles: p.groups.filter((g) => ["doc-admins", "compliance", "operators"].includes(g)),
           samples: ["How long should I rub hands with alcohol-based rub?", "What is the fall risk reassessment schedule?"],
           profile: "lite", llm_provider: "fake", llm_external: false, department: "Emergency Medicine", hospital };
}

const SNIPPET = "Rub all surfaces of both hands with alcohol-based hand rub for 20 to 30 seconds until dry.";
export const hits: SearchHit[] = [
  { chunk_id: "c2", document_id: "d1", version_id: "v2", title: "Hand Hygiene Policy", version_number: 2,
    category: "Infection Control", department: "Infection Prevention", classification: "internal",
    section: "Hand Hygiene Policy > Alcohol-based hand rub", page: 1, score: 0.62, snippet: SNIPPET,
    highlights: [[SNIPPET.indexOf("alcohol"), SNIPPET.indexOf("alcohol") + 7]] },
  { chunk_id: "c9", document_id: "d2", version_id: "v9", title: "Contact and Droplet Isolation Precautions",
    version_number: 1, category: "Infection Control", department: "Infection Prevention", classification: "internal",
    section: "Contact precautions", page: 1, score: 0.39, snippet: "Wear a gown and gloves on entering the room.",
    highlights: [] },
];

export const docDetail: DocumentDetail = {
  document_id: "d1", title: "Hand Hygiene Policy", category: "Infection Control", department: "Infection Prevention",
  classification: "internal", owner_id: "alex", active_version_id: "v2", retired_at: null, created_at: "2026-11-01",
  groups: ["all-staff"],
  versions: [
    { version_id: "v2", version_number: 2, status: "READY", stage: null, chunks_total: 2, chunks_embedded: 2,
      uploaded_by: "alex", approved_by: "taylor", approved_at: "2026-11-20T10:00:00Z", effective_date: "2026-11-20",
      review_due: "2027-11-20", error_code: null, error: null, created_at: "2026-11-19", filename: "hand-v2.md" },
    { version_id: "v1", version_number: 1, status: "SUPERSEDED", stage: null, chunks_total: 2, chunks_embedded: 2,
      uploaded_by: "alex", approved_by: "taylor", approved_at: "2026-01-05T10:00:00Z", effective_date: "2026-01-05",
      review_due: "2027-01-05", error_code: null, error: null, created_at: "2026-01-04", filename: "hand-v1.md" },
  ],
};

export function versionText(versionId: string): VersionText {
  const version = docDetail.versions.find((v) => v.version_id === versionId)!;
  return {
    document: { document_id: "d1", title: "Hand Hygiene Policy", category: "Infection Control",
                classification: "internal", active_version_id: "v2" },
    version,
    chunks: [
      { chunk_id: "c1", chunk_index: 0, page: 1, section: "Hand Hygiene Policy > Purpose",
        text: "Clean hands are the most effective way to prevent infection." },
      { chunk_id: "c2", chunk_index: 1, page: 1, section: "Hand Hygiene Policy > Alcohol-based hand rub",
        text: version.version_number === 2 ? SNIPPET : "Rub hands for at least 15 seconds." },
    ],
  };
}
