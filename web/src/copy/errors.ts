/** Plain-language explanations for backend error codes (UX-10). */
export const ERRORS: Record<string, string> = {
  unsupported_type: "Only .txt, .md and text-based .pdf files are supported.",
  too_large: "Files must be at most 10 MB.",
  pdf_malformed: "This PDF could not be read. Export it again and upload the new file.",
  pdf_encrypted: "This PDF is password-protected. Upload an unencrypted copy.",
  pdf_no_text_layer: "This PDF has no text layer (it looks scanned). Upload a text-based PDF.",
  invalid_encoding: "This file is not plain text. Save it as UTF-8 text or Markdown.",
  empty_document: "This file has no text in it.",
  max_retries_exceeded: "Processing failed five times. An operator can replay it from Operations.",
  self_approval: "You cannot approve a version you uploaded.",
  not_pending: "This version has already been decided.",
  idempotency_conflict: "This upload was already submitted with different content. Start a new upload.",
  invalid_category: "Choose a category from the list.",
  invalid_groups: "Choose at least one group who may read this document.",
  invalid_title: "Give the document a title of up to 200 characters.",
  db_unavailable: "The database is unavailable. Try again in a few seconds.",
  queue_unavailable: "The work queue is unavailable. Try again in a few seconds.",
  forbidden: "Your role doesn't allow this.",
  unauthenticated: "Sign in again.",
};

export function describeError(code: string | null | undefined): string {
  if (!code) return "";
  return ERRORS[code] ?? `Something went wrong (${code}).`;
}

export const GROUP_NAMES: Record<string, string> = {
  "all-staff": "Everyone on staff", clinical: "Clinical staff", physicians: "Physicians", nursing: "Nurses",
  pharmacy: "Pharmacists",
};
