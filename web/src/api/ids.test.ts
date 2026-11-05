// Covers: UX-10 (the upload wizard works on plain-HTTP origins where crypto.randomUUID is unavailable)
import { newIdempotencyKey } from "./ids";

test("falls back when crypto.randomUUID is unavailable", () => {
  const original = crypto.randomUUID;
  Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true });
  try {
    const a = newIdempotencyKey();
    const b = newIdempotencyKey();
    expect(a).toMatch(/^[0-9a-f-]{36}$/);
    expect(a).not.toBe(b);
  } finally {
    Object.defineProperty(crypto, "randomUUID", { value: original, configurable: true });
  }
});
