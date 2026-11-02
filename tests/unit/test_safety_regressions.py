"""Covers: AG-2, AG-3, CP-2, CP-3, CR-2, CR-6, CR-7.

Dependency-free regression checks for the guarded answer pipeline. Run with either
pytest or python -m unittest tests.unit.test_safety_regressions.
"""
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from assistant.answer import ChatDeps, answer
from assistant.citations import verify
from assistant.classify import Classification
from assistant.clinical import check
from assistant.types import Passage
from common.llm import ProviderInfo
from common.llm.fake import FakeLLM
from common.models import User

TEXT = "Call the rapid response team for systolic blood pressure below 90 or heart rate above 130."
PASSAGE = Passage(1, "chunk-v1", "doc", "Rapid Response", 1, "Activation", 1,
                  "internal", TEXT, 0.85, "version-1", "Emergency Response")


class ClinicalQuoteTests(unittest.TestCase):
    def test_word_overlap_does_not_exempt_a_patient_order(self):
        source = replace(PASSAGE, text="The protocol lists ceftriaxone 2 g for review by the pharmacy team.")
        self.assertTrue(check("Give ceftriaxone 2 g to the patient [1].", [source]).blocked)

    def test_exact_unsafe_text_requires_explicit_quotation(self):
        source = replace(PASSAGE, text="Give ceftriaxone 2 g to the patient.")
        self.assertTrue(check("Give ceftriaxone 2 g to the patient [1].", [source]).blocked)

    def test_explicit_exact_protocol_quote_is_allowed(self):
        source = replace(PASSAGE, text="Give ceftriaxone 2 g to the patient.")
        self.assertFalse(check('Our protocol says: "Give ceftriaxone 2 g to the patient." [1]', [source]).blocked)

    def test_invented_quote_is_blocked(self):
        source = replace(PASSAGE, text="Give ceftriaxone 1 g to the patient.")
        self.assertTrue(check('Our protocol says: "Give ceftriaxone 2 g to the patient." [1]', [source]).blocked)

    def test_quoted_dose_cannot_be_wrapped_in_a_patient_order(self):
        source = replace(PASSAGE, text="Give ceftriaxone 2 g after the supervising physician confirms the order.")
        draft = 'You should "give ceftriaxone 2 g" to this patient now [1].'
        self.assertTrue(check(draft, [source]).blocked)

    def test_protocol_quote_cannot_append_a_patient_instruction(self):
        source = replace(PASSAGE, text="Give ceftriaxone 2 g after the supervising physician confirms the order.")
        draft = 'Our protocol says: "Give ceftriaxone 2 g" so use that for this patient [1].'
        self.assertTrue(check(draft, [source]).blocked)

    def test_quote_cannot_drop_a_protocol_condition(self):
        source = replace(PASSAGE, text="Give ceftriaxone 2 g after the supervising physician confirms the order.")
        self.assertTrue(check('Our protocol says: "Give ceftriaxone 2 g" [1].', [source]).blocked)

    def test_short_uncited_claim_is_removed(self):
        report = verify("Sepsis is confirmed. " + TEXT.rstrip(".") + " [1].", [PASSAGE])
        self.assertNotIn("Sepsis is confirmed", report.kept_text)
        self.assertEqual(report.removed, 1)

    def test_citation_in_middle_does_not_cover_trailing_claim(self):
        report = verify(TEXT.rstrip(".") + " [1] and sepsis is confirmed.", [PASSAGE])
        self.assertEqual(report.kept_text, "")


class HistoryBoundaryTests(unittest.TestCase):
    def history(self, rows, allowed, external=True, maximum="internal"):
        from assistant.history import permitted_turns
        return permitted_turns(rows, allowed, external, maximum)

    def test_restricted_prior_answer_is_not_sent_to_external_provider(self):
        citation = PASSAGE.card() | {"classification": "restricted"}
        rows = [("user", "Waste policy?", None), ("assistant", "Restricted procedure [1].", [citation])]
        allowed = {PASSAGE.chunk_id: citation}
        self.assertEqual(self.history(rows, allowed), [])
        self.assertEqual(self.history(rows, allowed, external=False), [("Waste policy?", "Restricted procedure [1].")])

    def test_old_or_inaccessible_source_removes_the_whole_turn(self):
        rows = [("user", "Which threshold?", None), ("assistant", "Old threshold [1].", [PASSAGE.card()])]
        self.assertEqual(self.history(rows, {}), [])
        updated = PASSAGE.card() | {"version_id": "version-2"}
        self.assertEqual(self.history(rows, {PASSAGE.chunk_id: updated}), [])

    def test_history_uses_current_classification_and_redacts_identifiers(self):
        rows = [("user", "Patient John Smith MRN 00482913: threshold?", None),
                ("assistant", TEXT + " [1].", [PASSAGE.card()])]
        allowed = {PASSAGE.chunk_id: PASSAGE.card()}
        turns = self.history(rows, allowed)
        self.assertEqual(len(turns), 1)
        self.assertNotIn("00482913", turns[0][0])
        allowed[PASSAGE.chunk_id] = PASSAGE.card() | {"classification": "restricted"}
        self.assertEqual(self.history(rows, allowed), [])

    def test_permitted_history_preserves_source_classifications(self):
        rows = [("user", "Threshold?", None), ("assistant", TEXT + " [1].", [PASSAGE.card()])]
        turns = self.history(rows, {PASSAGE.chunk_id: PASSAGE.card()})
        self.assertEqual(turns.classifications, {"internal"})


class AnswerBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sources = [PASSAGE]
        self.cache = {}
        self.saved = []
        self.retrieved = []
        self.audits = []
        self.history = []
        self.user = User("sam", frozenset({"clinical", "nursing"}))
        self.llm = FakeLLM()
        self.settings = SimpleNamespace(phi_mode="redact", min_relevance=0.35,
                                        confidence_weights=(0.5, 0.3, 0.2), external_max_classification="internal",
                                        deployment_profile="hybrid", llm_answer_timeout_seconds=15.0)

        async def retrieve(user, question, label):
            self.retrieved.append(question)
            return self.sources[:]

        async def save(user, conversation_id, question, final):
            self.saved.append(question)
            return conversation_id or "conversation"

        async def history(user, conversation_id):
            return self.history

        async def audit(user, action, detail):
            self.audits.append((action, detail))

        async def cache_get(key):
            return self.cache.get(key)

        async def cache_put(key, value, document_ids):
            self.cache[key] = value

        self.deps = ChatDeps(retrieve, self.llm, self.settings, save, history, audit, cache_get, cache_put)
        # Classification is independent of these privacy/cache/output boundary tests.
        self.classifier = patch("assistant.answer.classify", return_value=Classification("policy_lookup"))
        self.classifier.start()
        self.addCleanup(self.classifier.stop)

    async def ask(self, question="What are the rapid response activation criteria?"):
        events = [event async for event in answer(question, self.user, "Nurse", None, self.deps)]
        return events[-1].data

    async def test_phi_is_removed_before_retrieval(self):
        await self.ask("Patient John Smith MRN 00482913: what are the rapid response criteria?")
        self.assertNotIn("John Smith", self.retrieved[0])
        self.assertNotIn("00482913", self.retrieved[0])
        # Placeholders match nothing and polluted the search; retrieval gets the question without them.
        self.assertNotIn("[REDACTED", self.retrieved[0])
        self.assertIn("what are the rapid response criteria?", self.retrieved[0])

    async def test_new_version_cannot_reuse_old_answer_even_after_late_cache_write(self):
        await self.ask()
        # Simulates a v1 request writing its cache after v2 finalize invalidated old entries.
        updated = "Call the rapid response team for systolic blood pressure below 85 or heart rate above 135."
        self.sources = [replace(PASSAGE, text=updated, version_id="version-2", version_number=2, chunk_id="chunk-v2")]
        final = await self.ask()
        self.assertIn("135", final["answer"])
        self.assertNotIn("130", final["answer"])
        self.assertFalse(final["receipt"]["cached"])

    async def test_changed_citation_order_cannot_remap_cached_claim(self):
        other = replace(PASSAGE, chunk_id="other", document_id="other-doc", version_id="other-v1",
                        text="Escalate a fall to the nursing supervisor and complete an incident report.")
        self.sources = [PASSAGE, other]
        await self.ask()
        self.sources.reverse()
        final = await self.ask()
        self.assertFalse(final["receipt"]["cached"])
        self.assertEqual(len(self.llm.calls), 2)

    async def test_history_changes_do_not_reuse_context_free_cache(self):
        await self.ask()
        self.history = [("Which activation criteria?", "The rapid response criteria.")]
        final = await self.ask()
        self.assertFalse(final["receipt"]["cached"])
        self.assertEqual(len(self.llm.calls), 2)

    async def test_unchanged_context_reuses_verified_cache(self):
        await self.ask()
        final = await self.ask()
        self.assertTrue(final["receipt"]["cached"])
        self.assertEqual(len(self.llm.calls), 1)

    async def test_egress_block_is_audited_with_withheld_classifications(self):
        self.llm.info = ProviderInfo("external", "openai_compatible", "", "model", "", True, False, True, "us")
        self.sources = [replace(PASSAGE, classification="restricted")]
        await self.ask()
        decisions = [detail for action, detail in self.audits if action == "egress.llm_call"]
        self.assertTrue(decisions)
        self.assertEqual(decisions[0]["decision"], "fallback_passages_only")
        self.assertEqual(decisions[0]["withheld"], {"restricted": 1})
        self.assertEqual(self.llm.calls, [])

    async def test_egress_audit_includes_permitted_history_classifications(self):
        from assistant.history import permitted_turns
        self.llm.info = ProviderInfo("external", "openai_compatible", "", "model", "", True, False, True, "us")
        rows = [("user", "Criteria?", None), ("assistant", TEXT + " [1].", [PASSAGE.card()])]
        self.history = permitted_turns(rows, {PASSAGE.chunk_id: PASSAGE.card()}, True, "internal")
        self.sources = [replace(PASSAGE, classification="public")]
        await self.ask()
        calls = [detail for action, detail in self.audits if action == "egress.llm_call"]
        # The follow-up is first condensed into a search query (history only), then answered (history + passages).
        self.assertEqual([c["decision"] for c in calls][0], "condense_query")
        self.assertEqual(calls[0]["classifications"], ["internal"])
        decision = next(c for c in calls if c["decision"] != "condense_query")
        self.assertEqual(decision["classifications"], ["internal", "public"])


if __name__ == "__main__":
    unittest.main()
