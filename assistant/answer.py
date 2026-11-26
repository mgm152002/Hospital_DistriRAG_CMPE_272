"""Guarded answer pipeline (spec 5.3): PHI screen → classify → banner → retrieve → egress policy → prompt →
generate (or passages-only) → output guards → confidence → receipt. I/O is injected through ChatDeps."""
import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from assistant import relevance
from assistant.citations import verify
from assistant.classify import REFUSING, classify
from assistant.clinical import check
from assistant.confidence import Confidence, band_for, score
from assistant.contextualize import condense
from assistant.egress_policy import decide
from assistant.extract import Extract, emergency_lead, extract
from assistant.injection import redact_secrets, strip_injection
from assistant.phi import screen
from assistant.prompt import build_messages
from assistant.types import Passage
from common.llm import ProviderUnavailable

DISCLAIMER = "Reference only. Verify against the source and use clinical judgement."
REFUSAL = "I can't make a diagnosis or patient-specific recommendation. These are the relevant hospital documents."
NO_SOURCE = "I couldn't find this in approved documents you can access."
ORDER_REFUSAL = ("I can't give or calculate doses or orders for a patient. Contact the pharmacy for dosing or "
                 "request a pharmacy consult; these are the relevant hospital documents.")
DIAGNOSIS_NEXT = " Use the criteria and escalation steps in these documents, and escalate to the responsible provider."
HEDGE_RECOVERED = "The answer service could not summarise this; here is the closest text from the source."
NEXT_STEP = ("Try different words or a more specific question, or ask the knowledge administrator whether a document "
             "covers this.")
EXTRACTIVE_CAP = 74  # verbatim, but not checked against the question: never High
OUTAGE = "The answer service is unavailable; here are the most relevant passages."
EGRESS = ("These documents can't be sent to the external answer service under the data policy; "
          "here are the most relevant passages.")
UNVERIFIED = "I couldn't verify a cited answer; here are the most relevant passages."
OUT_OF_SCOPE = "I can help with hospital policies, procedures and clinical reference documents."
PHI_BLOCKED = ("This looks like it contains patient information, so it was not searched or sent to the AI model. "
               "Remove names, record numbers, dates of birth and contact details, then ask again.")
EMERGENCY = "If this is happening now, activate the Rapid Response / Code team per hospital procedure."
# When the policy's own words are shown instead of a generated answer, one plain line says why; a quote that needs no
# explanation gets no note.
NOTES = {
    EGRESS: "This policy is confidential, so it is quoted here instead of being sent to the AI model.",
    OUTAGE: "The AI service is unavailable, so this is the source's own wording.",
    UNVERIFIED: "The AI answer could not be checked against the policy, so this is the policy's own wording.",
}
MAX_PASSAGES = 6


def mask_passages(passages: list[Passage]) -> list[Passage]:
    """The copy of the passages sent to the model, with personal identifiers replaced by placeholders."""
    return [replace(p, text=screen(p.text).redacted, title=screen(p.title).redacted) for p in passages]


def not_found(role: str) -> str:
    """No dead end: say what was searched, why it may be empty for this role, and what to do next."""
    scope = f" Your role ({role}) may not cover this topic." if role else ""
    return (f"{NO_SOURCE}{scope} Try different words or a more specific question, or ask the knowledge administrator "
            "whether a document exists or whether you need access.")


def refusal(label: str) -> str:
    return ORDER_REFUSAL if label == "patient_order" else REFUSAL + DIAGNOSIS_NEXT


def closest(question: str, passages: list[Passage], lead: Extract) -> Extract:
    """The policy's own sentences for a fallback answer: the emergency action first, then the best matches.
    A quote that does not itself address the question is dropped: "rub alcohol on an open wound" must not be answered
    with the hand-rub sentence just because both mention alcohol."""
    seen = {i.sentence for i in lead.items}
    # A sentence carrying personal details (a phone number, an email) is never quoted: generated answers are screened
    # for these, and a quote must not be the way round that screen.
    # Filter before ranking: rejected contact lines must not crowd every useful sentence out of the top two.
    relevant = extract(question, passages, accept=lambda text, source: (
        text not in seen and not screen(text).found
        and relevance.quote_coverage(question, text, source.title) >= relevance.QUOTE_MIN))
    return Extract([*lead.items, *relevant.items][:2])


@dataclass
class ChatEvent:
    type: str
    data: dict[str, Any]


@dataclass
class ChatDeps:
    retrieve: Callable[[Any, str, str], Awaitable[list[Passage]]]
    llm: Any
    settings: Any
    save: Callable[[Any, str | None, str, dict], Awaitable[str]]
    history: Callable[[Any, str | None], Awaitable[list[tuple[str, str]]]]
    audit: Callable[[Any, str, dict], Awaitable[None]]
    cache_get: Callable[[str], Awaitable[dict | None]]
    cache_put: Callable[[str, dict, list[str]], Awaitable[None]]


# Bump when a guard changes what an answer may say: cached answers made under older guards must not be served.
# 3: hedge recovery, relevance gate, extractive fallbacks, emergency lead, redaction-free retrieval.
# 4: conversational prompt, model-condensed follow-up queries, markdown-aware citation check, hedges trusted (no quote
#    recovery from a merged follow-up query).
GUARD_VERSION = 6  # 6: an instruction at the start of a list item is not a name; 5: places are not people


def cache_key(question: str, groups: Any, label: str, provider: str, passages: list[Passage],
              history: list[tuple[str, str]], role: str, model: str, guard_version: int | None = None) -> str:
    norm = " ".join(question.lower().split())
    # Bind source numbers to their exact passages and versions. Invalidation alone
    # races with an older request that writes its cache after a new version publishes.
    version = GUARD_VERSION if guard_version is None else guard_version
    context = {"guard_version": version, "question": norm, "groups": sorted(groups or []), "label": label,
               "provider": provider, "model": model, "role": role,
               "passages": [p.card() for p in passages], "history": history[-6:]}
    return hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def answer(question: str, user: Any, role: str, conversation_id: str | None,
                 deps: ChatDeps) -> AsyncIterator[ChatEvent]:
    started = time.perf_counter()
    s, info = deps.settings, deps.llm.info
    phi = screen(question)
    receipt: dict[str, Any] = {"classification": None, "phi_redacted": phi.found, "provider": info.name,
                               "model": info.model, "external": info.external, "egress_decision": "none",
                               "passages_withheld": {}, "checks": {"citations": "n/a", "clinical": "n/a",
                                                                   "injection": "pass"},
                               "fallback": None, "cached": False, "latency_ms": 0}
    if phi.found:
        notice = phi.notice
        if s.phi_mode == "block":  # nothing was searched: say what was found, not what was removed
            notice = notice.replace("Removed ", "Not sent: found ", 1).replace(" before searching.", ".")
        yield ChatEvent("phi", {"types": sorted({f.type for f in phi.findings}), "notice": notice})
    lead = Extract()  # replaced for an emergency once the passages are known
    cls = classify(phi.redacted)
    receipt["classification"] = cls.label
    yield ChatEvent("classification", {"label": cls.label, "method": cls.method})

    async def finish(text: str, passages: list[Passage], cited: list[int], coverage: float,
                     fallback: str | None, action: str = "chat.answered", verbatim: float = 0.0,
                     cap: int | None = None, note: str | None = None) -> ChatEvent:
        receipt["fallback"] = fallback
        receipt["latency_ms"] = round((time.perf_counter() - started) * 1000)
        cited_passages = [p for p in passages if p.index in cited] or passages[:3]
        conf = score([p.score for p in cited_passages], coverage, len({p.document_id for p in cited_passages})
                     if cited else 0, s, verbatim)
        if cap is not None and conf.score > cap:
            conf = Confidence(cap, band_for(cap), conf.r, conf.c, conf.a)
        body = text if text.endswith(DISCLAIMER) else f"{text}\n\n{DISCLAIMER}"
        # Each passage says whether the answer cited it, so a reopened conversation never claims a source it never used.
        data = {"answer": body, "citations": [{**p.card(), "cited": p.index in cited} for p in cited_passages],
                "cited": cited,
                "confidence": conf.score, "band": conf.band, "parts": {"r": conf.r, "c": conf.c, "a": conf.a},
                "receipt": receipt, "fallback": fallback, "note": note}
        data["conversation_id"] = await deps.save(user, conversation_id, phi.redacted, data)
        await deps.audit(user, action, {"label": cls.label, "provider": info.name, "egress": receipt["egress_decision"],
                                        "confidence": conf.score, "fallback": fallback, "phi": phi.found})
        return ChatEvent("final", data)

    async def finish_quoted(prefix: str, ex: Extract, passages: list[Passage], fallback: str) -> ChatEvent:
        """A fallback that quotes the policy. Nothing quoted means nothing was verified: no label, no confidence."""
        if not ex.items:
            return await finish(prefix, passages, [], 0.0, fallback)
        receipt["mode"] = "extractive"
        return await finish(ex.text, passages, ex.cited, 1.0, fallback, verbatim=1.0, cap=EXTRACTIVE_CAP,
                            note=NOTES.get(prefix))

    if phi.found and s.phi_mode == "block":
        yield await finish(PHI_BLOCKED, [], [], 0.0, "phi_blocked", "chat.blocked")
        return
    if cls.label == "emergency":
        yield ChatEvent("banner", {"level": "emergency", "text": EMERGENCY})
    if cls.label == "out_of_scope":
        yield ChatEvent("sources", {"passages": []})
        yield await finish(OUT_OF_SCOPE, [], [], 0.0, "out_of_scope")
        return

    history = await deps.history(user, conversation_id)
    # Identifiers removed and placeholders dropped ("[REDACTED-NAME]" matches nothing). A follow-up is rewritten into a
    # standalone search query ("should I rub it on an open wound" -> "alcohol hand rub on an open wound") by the model,
    # or by borrowing the previous question when no model is available. The query is for retrieval only: anything
    # quoted to the user is matched against what the user actually asked (`own`), never against the merged query.
    own = phi.search_text
    query = own
    if history and own.strip():
        if info.external:  # the same redacted, provider-eligible turns the answer prompt will carry
            sent = sorted(getattr(history, "classifications", ()))
            await deps.audit(user, "egress.llm_call", {"provider": info.name, "decision": "condense_query",
                                                      "classifications": sent, "withheld": {}, "called": True})
        query = await condense(own, history, deps.llm,
                               getattr(s, "llm_condense_timeout_seconds", None) or 4.0)
    raw = (await deps.retrieve(user, query, cls.label))[:MAX_PASSAGES] if query.strip() else []
    passages: list[Passage] = []
    for i, p in enumerate(raw, start=1):
        text, changed = strip_injection(p.text)
        if changed:
            receipt["checks"]["injection"] = "stripped"
        passages.append(replace(p, index=i, text=text))
    relevant = [p for p in passages if p.score >= s.min_relevance]
    if cls.label in REFUSING:  # declined whether or not related passages were found
        yield ChatEvent("sources", {"passages": [p.card() for p in relevant]})
        yield await finish(refusal(cls.label), relevant, [], 0.0, "refused", "chat.blocked")
        return
    lead = emergency_lead(relevant) if cls.label == "emergency" else Extract()
    # An emergency whose documents say who to call is always answerable; otherwise weak retrieval must also share
    # the question's words, or the answer would be a cited passage about something else.
    if not (lead.items or relevance.supports_question(query, relevant, s.min_relevance)):
        yield ChatEvent("sources", {"passages": []})
        yield await finish(not_found(role), [], [], 0.0, "no_sources")
        return
    yield ChatEvent("sources", {"passages": [p.card() for p in relevant]})
    first = (lead if lead.items else closest(own, relevant, lead)).items[:1]
    if first:
        top = next(p for p in relevant if p.index == first[0].index)
        yield ChatEvent("preview", {"index": top.index, "title": top.title, "version_number": top.version_number,
                                    "section": top.section, "text": first[0].sentence})

    egress = decide(info, relevant, s)
    receipt["egress_decision"] = egress.decision
    receipt["passages_withheld"] = egress.withheld
    # If the best match is one the policy keeps from the external model, do not ask it about whatever is left: it can
    # only answer from an unrelated passage. Quote the withheld policy to the user locally instead.
    kept_back = [p.score for p in relevant if p not in egress.allowed]
    outranked = bool(kept_back) and (not egress.allowed or max(kept_back) > max(p.score for p in egress.allowed))
    if outranked:
        receipt["egress_decision"] = "fallback_passages_only"
    if egress.decision == "fallback_passages_only" or outranked:
        await deps.audit(user, "egress.llm_call", {"provider": info.name, "decision": egress.decision,
                                                  "classifications": [], "withheld": egress.withheld,
                                                  "called": False})
        ex = closest(own, relevant, lead)
        yield await finish_quoted(EGRESS, ex, relevant, "egress_policy")
        return

    key = cache_key(phi.redacted, getattr(user, "groups", None), cls.label, info.name,
                    egress.allowed, history, role, info.model)
    cached = None if phi.found else await deps.cache_get(key)
    if cached:
        receipt["cached"] = True
        receipt["checks"].update(cached.get("checks", {"citations": "pass", "clinical": "pass"}))
        for word in cached["text"].split(" "):
            yield ChatEvent("token", {"text": word + " "})
        yield await finish(cached["text"], egress.allowed, cached["cited"], cached["coverage"], None,
                           verbatim=cached.get("verbatim", 0.0))
        return

    # The model never sees personal details from the documents either: names, phone numbers, emails, dates of birth and
    # record numbers in a passage are masked in the copy it receives. The reader still sees the original source.
    masked = mask_passages(egress.allowed)
    receipt["pii_masked"] = sum(p.text != q.text or p.title != q.title for p, q in zip(egress.allowed, masked,
                                                                                               strict=True))
    messages = build_messages(phi.redacted, masked, role, history)
    if info.external:
        sent_classes = {p.classification for p in egress.allowed} | set(getattr(history, "classifications", ()))
        await deps.audit(user, "egress.llm_call", {"provider": info.name, "decision": egress.decision,
                                                  "classifications": sorted(sent_classes),
                                                  "withheld": egress.withheld, "called": True})
    try:
        # Bound queueing, retries and streaming together; a slow/free provider must not stall the answer indefinitely.
        async with asyncio.timeout(s.llm_answer_timeout_seconds):
            draft = "".join([token async for token in deps.llm.stream(messages)])
        if not draft.strip():
            raise ProviderUnavailable("the model returned an empty answer")
    except (ProviderUnavailable, Exception) as error:  # any provider failure degrades to passages-only (RL-10)
        receipt["error"] = type(error).__name__
        status = getattr(error, "status_code", None)
        if status is not None:
            receipt["provider_status"] = status
        ex = closest(own, relevant, lead)
        yield await finish_quoted(OUTAGE, ex, relevant, "provider_unavailable")
        return

    draft, _ = redact_secrets(draft)
    draft = screen(draft).redacted
    safety = check(draft, masked)
    if safety.blocked:
        receipt["checks"]["clinical"] = "blocked"
        yield await finish(REFUSAL, relevant, [], 0.0, "clinical_guard", "chat.blocked")
        return
    receipt["checks"]["clinical"] = "pass"
    hedged = relevance.is_hedge(draft)
    unseen = [p for p in relevant if p not in egress.allowed]
    if (hedged and unseen) or relevance.only_changelog(draft):
        # The model could not speak for passages it was never shown (withheld by the data policy), and a reply that is
        # only a version note answers nothing. Quote locally, matched against the user's own question.
        ex = closest(own, unseen if hedged else relevant, lead)
        if ex.items:
            yield await finish_quoted(HEDGE_RECOVERED, ex, relevant, "model_hedge")
            return
        if not hedged:
            yield await finish(not_found(role), [], [], 0.0, "no_sources")
            return
    report = verify(draft, masked)
    if hedged and (not report.cited_ids or relevance.coverage(query, [p for p in egress.allowed
                                                                     if p.index in report.cited_ids])
                   < relevance.MIN_COVERAGE):
        # The model says the documents do not answer this. Trust it: its own words, no near-miss quote.
        receipt["checks"]["citations"] = "pass"
        said = " ".join(line for line in report.kept_text.split("\n") if line and "[" not in line).strip()
        yield await finish(f"{said} {NEXT_STEP}" if said else not_found(role), [], [], 0.0, "no_sources")
        return
    if not report.cited_ids or (report.factual and report.removed / report.factual > 0.5):
        receipt["checks"]["citations"] = "fail"
        ex = closest(own, egress.allowed, lead)
        yield await finish_quoted(UNVERIFIED, ex, egress.allowed, "citations")
        return
    receipt["checks"]["citations"] = "pass" if report.removed == 0 else f"removed {report.removed}"
    text, cited_ids = report.kept_text, report.cited_ids
    if lead.items and lead.items[0].sentence not in text:  # an emergency answer starts with who to call
        text, cited_ids = f"{lead.text}\n\n{text}", sorted({*cited_ids, *lead.cited})
    for word in text.split(" "):
        yield ChatEvent("token", {"text": word + " "})
    if not phi.found:
        await deps.cache_put(key, {"text": text, "cited": cited_ids, "coverage": report.coverage,
                                   "verbatim": report.verbatim,
                                   "checks": {"citations": receipt["checks"]["citations"], "clinical": "pass"}},
                             sorted({p.document_id for p in egress.allowed if p.index in cited_ids}))
    yield await finish(text, egress.allowed, cited_ids, report.coverage, None, verbatim=report.verbatim)
