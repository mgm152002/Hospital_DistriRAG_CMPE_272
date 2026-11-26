"""Prompt-injection stripping and secret redaction (AG-6), carried over from the original agent/guard.py."""
import re

INJECTION = re.compile(
    r"(system instruction|instruction for the assistant|ignore (all|any|previous|prior|other|the)\b"
    r"|disregard (all|any|previous|the)\b|you are now|new instructions|assistant:"
    r"|tell (users|them|anyone|everyone|the user) to|(email|send|share) (their|your) (password|credentials))",
    re.IGNORECASE,
)
SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
SECRETS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(password|passwd|secret|api[_ -]?key|token)\s*[:=]\s*\S+"),
)
REDACTED = "[redacted]"


def strip_injection(text: str) -> tuple[str, bool]:
    sentences = SENTENCE.findall(text)
    kept = [s for s in sentences if not INJECTION.search(s)]
    if len(kept) == len(sentences):
        return text, False
    return " ".join(s.strip() for s in kept if s.strip()), True


def redact_secrets(text: str) -> tuple[str, int]:
    count = 0
    for pattern in SECRETS:
        text, n = pattern.subn(REDACTED, text)
        count += n
    return text, count
