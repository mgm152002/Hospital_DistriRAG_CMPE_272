import { request as playwrightRequest } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:8000";

/**
 * Delete the documents a spec created, so the shared demo database does not collect "Quiet Hours Policy xyz" and
 * "Synthetic Ward Guide 123" entries that then appear in other people's search. Lists as Alex, deletes as Taylor
 * (only compliance may delete); works with local accounts and with the header-persona demo mode.
 */
export async function removeDocuments(titles: string[]) {
  const as = async (persona: string) => {
    const ctx = await playwrightRequest.newContext({ baseURL: BASE_URL, extraHTTPHeaders: { "X-User-Id": persona } });
    await ctx.post(`/api/auth/demo/${persona}`); // 404 in header mode; the X-User-Id header covers it
    return ctx;
  };
  const alex = await as("alex");
  const taylor = await as("taylor");
  try {
    const docs: { document_id: string; title: string }[] = await (await alex.get("/api/documents")).json();
    for (const doc of docs.filter((d) => titles.includes(d.title))) {
      await taylor.delete(`/api/documents/${doc.document_id}`);
    }
  } finally {
    await alex.dispose();
    await taylor.dispose();
  }
}
