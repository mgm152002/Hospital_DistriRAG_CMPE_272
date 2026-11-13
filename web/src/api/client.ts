/** Fetch wrapper: adds the signed-in persona, maps errors to ApiError, and reads SSE streams over POST/GET. */
const USER_KEY = "distrirag.user";

export class ApiError extends Error {
  constructor(public status: number, public code: string, public detail: string, public retryAfter?: number) {
    super(detail);
  }
}

export const session = {
  get: () => localStorage.getItem(USER_KEY),
  set: (userId: string) => localStorage.setItem(USER_KEY, userId),
  clear: () => localStorage.removeItem(USER_KEY),
};

function headers(extra?: HeadersInit): Headers {
  const h = new Headers(extra);
  const user = session.get();
  if (user) h.set("X-User-Id", user);
  return h;
}

async function fail(response: Response): Promise<never> {
  let code = "http_" + response.status;
  let detail = response.statusText || "Request failed";
  try {
    const body = await response.json();
    code = body.error_code ?? code;
    detail = body.detail ?? detail;
  } catch { /* not JSON */ }
  const retry = Number(response.headers.get("Retry-After")) || undefined;
  throw new ApiError(response.status, code, detail, retry);
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, headers: headers(init.headers) });
  if (!response.ok) await fail(response);
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") ?? "";
  return (type.includes("json") ? response.json() : response.text()) as Promise<T>;
}

export const postJson = <T,>(path: string, body: unknown, extra?: HeadersInit) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json", ...extra } });

export interface SseEvent { event: string; data: any }

/** Parse a text/event-stream body. Works for POST (EventSource cannot send our header or a body). */
export async function* readSse(response: Response): AsyncGenerator<SseEvent> {
  if (!response.ok) await fail(response);
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data.push(line.slice(6));
      }
      if (data.length) yield { event, data: JSON.parse(data.join("\n")) };
    }
  }
}

export async function* streamChat(message: string, conversationId?: string | null, signal?: AbortSignal) {
  const response = await fetch("/api/chat", {
    method: "POST", signal,
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({ message, conversation_id: conversationId ?? null }),
  });
  yield* readSse(response);
}

export async function* streamPipeline(signal?: AbortSignal) {
  yield* readSse(await fetch("/api/pipeline/events", { headers: headers(), signal }));
}
