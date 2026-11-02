"""Unit tests for the crew's adjudication logic, using a fake transport.

Test doubles live here, in tests/, only — never in the shipped path.
The behaviors pinned down:
  * the planner adjudicates ONLY when cross-verification disagrees;
  * on agreement the two parts are assembled untouched (no extra model call);
  * worker B's receipt honestly records grounded true/false;
  * an unparseable review escalates instead of silently passing.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proofcrew import crew as crew_mod
from proofcrew.config import Config

PLAN_JSON = json.dumps(
    {
        "plan": "do both halves",
        "worker_a_task": "PART-A: write the overview",
        "worker_b_task": "PART-B: write the current-facts section",
        "search_query": "current facts query",
    }
)
SCREEN_JSON = json.dumps(
    {
        "worker_a": {"pass": True, "notes": "fine"},
        "worker_b": {"pass": True, "notes": "fine"},
        "flags": [],
    }
)
AGREE = json.dumps({"verdict": "agree", "issues": []})


class FakeTransport:
    """Records every call; responds from a script keyed by system prompt."""

    def __init__(
        self,
        verify_a=AGREE,
        verify_b=AGREE,
        adjudicated_text="ADJUDICATED FINAL",
        screen_json=SCREEN_JSON,
    ):
        self.calls: list[tuple[str, str, str]] = []
        self._verify_by_target_output = {
            "Output B": verify_a,  # worker A verifies B's output
            "Output A": verify_b,  # worker B verifies A's output
        }
        self._adjudicated_text = adjudicated_text
        self._screen_json = screen_json

    def complete(self, model: str, system: str, user: str) -> str:
        self.calls.append((model, system, user))
        if system == crew_mod.PLAN_SYSTEM:
            return PLAN_JSON
        if system == crew_mod.WORKER_SYSTEM:
            return "Output A" if "PART-A" in user else "Output B"
        if system == crew_mod.SCREEN_SYSTEM:
            return self._screen_json
        if system == crew_mod.VERIFY_SYSTEM:
            for marker, response in self._verify_by_target_output.items():
                if marker in user:
                    return response
            raise AssertionError("verify prompt contained no known output")
        if system == crew_mod.ADJUDICATE_SYSTEM:
            return self._adjudicated_text
        raise AssertionError(f"unexpected system prompt: {system[:40]}")

    def count(self, system: str) -> int:
        return sum(1 for _, s, _ in self.calls if s == system)


class FakeTavily:
    def search(self, query: str, max_results: int = 5) -> list[dict]:
        return [
            {
                "title": "Fact page",
                "url": "https://example.com/fact",
                "content": "A current fact.",
            }
        ]


def test_config() -> Config:
    return Config(api_key="test-key", tavily_api_key=None)


class TestAdjudicationGate(unittest.TestCase):
    def test_needs_adjudication_truth_table(self):
        self.assertFalse(crew_mod.needs_adjudication({"verdict": "agree"}, {"verdict": "agree"}))
        self.assertTrue(crew_mod.needs_adjudication({"verdict": "disagree"}, {"verdict": "agree"}))
        self.assertTrue(crew_mod.needs_adjudication({"verdict": "agree"}, {"verdict": "disagree"}))
        # Unparseable / missing reviews must escalate, never silently pass.
        self.assertTrue(crew_mod.needs_adjudication(None, {"verdict": "agree"}))
        self.assertTrue(crew_mod.needs_adjudication({}, {}))

    def test_agreement_assembles_without_adjudication(self):
        transport = FakeTransport()
        result = crew_mod.run_crew("the task", transport, test_config())
        self.assertFalse(result.adjudicated)
        self.assertEqual(transport.count(crew_mod.ADJUDICATE_SYSTEM), 0)
        # Planner called exactly once (the plan) — not again for adjudication.
        planner_calls = [c for c in transport.calls if c[0] == test_config().planner_model]
        self.assertEqual(len(planner_calls), 1)
        self.assertIn("Output A", result.deliverable)
        self.assertIn("Output B", result.deliverable)
        kinds = [r["kind"] for r in result.chain.receipts]
        self.assertEqual(
            kinds,
            ["plan", "work", "work", "screen", "verify", "verify", "assembly", "final"],
        )

    def test_disagreement_triggers_adjudication(self):
        transport = FakeTransport(
            verify_b=json.dumps({"verdict": "disagree", "issues": ["A is wrong"]})
        )
        result = crew_mod.run_crew("the task", transport, test_config())
        self.assertTrue(result.adjudicated)
        self.assertEqual(transport.count(crew_mod.ADJUDICATE_SYSTEM), 1)
        self.assertEqual(result.deliverable, "ADJUDICATED FINAL")
        kinds = [r["kind"] for r in result.chain.receipts]
        self.assertIn("adjudication", kinds)
        self.assertNotIn("assembly", kinds)

    def test_unparseable_review_escalates(self):
        transport = FakeTransport(verify_a="I looked and it seems fine, no JSON here")
        result = crew_mod.run_crew("the task", transport, test_config())
        self.assertTrue(result.adjudicated)


class TestGroundingHonesty(unittest.TestCase):
    def test_no_tavily_key_means_grounded_false_in_receipt(self):
        transport = FakeTransport()
        result = crew_mod.run_crew("the task", transport, test_config(), tavily_client=None)
        self.assertFalse(result.grounded_worker_b)
        worker_b = next(
            r for r in result.chain.receipts if r["actor"] == "worker_b" and r["kind"] == "work"
        )
        self.assertIs(worker_b["payload"]["grounded"], False)

    def test_tavily_grounding_reaches_worker_b_and_receipt(self):
        transport = FakeTransport()
        result = crew_mod.run_crew(
            "the task", transport, test_config(), tavily_client=FakeTavily()
        )
        self.assertTrue(result.grounded_worker_b)
        worker_b = next(
            r for r in result.chain.receipts if r["actor"] == "worker_b" and r["kind"] == "work"
        )
        self.assertIs(worker_b["payload"]["grounded"], True)
        b_prompts = [
            user
            for _, system, user in transport.calls
            if system == crew_mod.WORKER_SYSTEM and "PART-B" in user
        ]
        self.assertTrue(any("https://example.com/fact" in p for p in b_prompts))

    def test_receipt_chain_from_a_run_verifies(self):
        from proofcrew.receipts import verify_receipts

        transport = FakeTransport()
        result = crew_mod.run_crew("the task", transport, test_config())
        self.assertEqual(verify_receipts(result.chain.receipts), [])


class MessyTavily:
    """Search results with a duplicate URL and an entry with no URL."""

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        return [
            {"title": "Fact page", "url": "https://example.com/fact", "content": "x"},
            {"title": "Fact page again", "url": "https://example.com/fact", "content": "y"},
            {"title": "No link at all", "url": "  ", "content": "z"},
            {"title": "Second source", "url": "https://example.org/other", "content": "w"},
        ]


class TestCitationsFirstClass(unittest.TestCase):
    """Citations are structured data, not text that may or may not survive:
    the Sources section of the final deliverable is built deterministically
    from exactly the URLs Tavily returned — present on both the assembly
    and the adjudication path when grounded, absent when not."""

    def test_grounded_agreement_deliverable_carries_sources(self):
        transport = FakeTransport()
        result = crew_mod.run_crew(
            "the task", transport, test_config(), tavily_client=FakeTavily()
        )
        self.assertFalse(result.adjudicated)
        self.assertEqual(
            result.sources,
            [{"title": "Fact page", "url": "https://example.com/fact"}],
        )
        self.assertIn("## Sources", result.deliverable)
        self.assertIn("[Fact page](https://example.com/fact)", result.deliverable)

    def test_grounded_adjudication_keeps_sources(self):
        transport = FakeTransport(
            verify_b=json.dumps({"verdict": "disagree", "issues": ["A is wrong"]})
        )
        result = crew_mod.run_crew(
            "the task", transport, test_config(), tavily_client=FakeTavily()
        )
        self.assertTrue(result.adjudicated)
        self.assertIn("ADJUDICATED FINAL", result.deliverable)
        self.assertIn("## Sources", result.deliverable)
        self.assertIn("https://example.com/fact", result.deliverable)
        # The adjudicator is told the real source list, so it cites
        # retrieved URLs rather than inventing its own.
        adjudicate_prompts = [
            user for _, system, user in transport.calls
            if system == crew_mod.ADJUDICATE_SYSTEM
        ]
        self.assertTrue(
            any("https://example.com/fact" in p for p in adjudicate_prompts)
        )

    def test_ungrounded_deliverable_has_no_sources_section(self):
        transport = FakeTransport()
        result = crew_mod.run_crew("the task", transport, test_config())
        self.assertEqual(result.sources, [])
        self.assertNotIn("## Sources", result.deliverable)
        # Honest absence: with no research call, no links appear at all.
        self.assertNotIn("http://", result.deliverable)
        self.assertNotIn("https://", result.deliverable)

    def test_sources_recorded_in_receipts(self):
        transport = FakeTransport()
        result = crew_mod.run_crew(
            "the task", transport, test_config(), tavily_client=FakeTavily()
        )
        worker_b = next(
            r for r in result.chain.receipts if r["actor"] == "worker_b" and r["kind"] == "work"
        )
        self.assertEqual(
            worker_b["payload"]["sources"],
            [{"title": "Fact page", "url": "https://example.com/fact"}],
        )
        final = result.chain.receipts[-1]
        self.assertEqual(final["kind"], "final")
        self.assertEqual(final["payload"]["citations"], ["https://example.com/fact"])
        # The final receipt's hash still pins the deliverable as emitted,
        # Sources section included.
        import hashlib

        self.assertEqual(
            final["payload"]["deliverable_sha256"],
            hashlib.sha256(result.deliverable.encode("utf-8")).hexdigest(),
        )

    def test_ungrounded_receipts_record_no_citations(self):
        transport = FakeTransport()
        result = crew_mod.run_crew("the task", transport, test_config())
        worker_b = next(
            r for r in result.chain.receipts if r["actor"] == "worker_b" and r["kind"] == "work"
        )
        self.assertEqual(worker_b["payload"]["sources"], [])
        self.assertEqual(result.chain.receipts[-1]["payload"]["citations"], [])

    def test_source_list_dedupes_and_drops_linkless_results(self):
        transport = FakeTransport()
        result = crew_mod.run_crew(
            "the task", transport, test_config(), tavily_client=MessyTavily()
        )
        self.assertEqual(
            result.sources,
            [
                {"title": "Fact page", "url": "https://example.com/fact"},
                {"title": "Second source", "url": "https://example.org/other"},
            ],
        )
        self.assertEqual(result.deliverable.count("https://example.com/fact"), 1)
        self.assertNotIn("No link at all", result.deliverable)


SCREEN_SUFFICIENT = json.dumps(
    {
        "worker_a": {"pass": True, "notes": "fine"},
        "worker_b": {
            "pass": True,
            "evidence_sufficient": True,
            "notes": "sources support the answer",
        },
        "flags": [],
    }
)
SCREEN_INSUFFICIENT = json.dumps(
    {
        "worker_a": {"pass": True, "notes": "fine"},
        "worker_b": {
            "pass": True,
            "evidence_sufficient": False,
            "notes": "retrieved sources do not answer the task; worker "
            "correctly concludes the evidence is insufficient",
        },
        "flags": [],
    }
)


class TestEvidenceSufficiencyGate(unittest.TestCase):
    """The screener's structured evidence_sufficient verdict gates every
    consumer of the source list together: an explicit false (retrieval
    returned pages, none on-point, worker B rightly declines) means no
    Sources section and empty final-receipt citations on BOTH the
    assembly and adjudication paths — while worker B's receipt keeps
    recording what was actually retrieved. True, or the field absent
    (legacy screens and fixtures), behavior is exactly as before."""

    def _screen_receipt(self, result):
        return next(
            r for r in result.chain.receipts
            if r["actor"] == "screener" and r["kind"] == "screen"
        )

    def test_insufficient_verdict_suppresses_sources_and_citations(self):
        transport = FakeTransport(screen_json=SCREEN_INSUFFICIENT)
        result = crew_mod.run_crew(
            "the task", transport, test_config(), tavily_client=FakeTavily()
        )
        # Retrieval happened and is still honestly recorded...
        self.assertFalse(result.adjudicated)
        self.assertEqual(
            result.sources,
            [{"title": "Fact page", "url": "https://example.com/fact"}],
        )
        worker_b = next(
            r for r in result.chain.receipts if r["actor"] == "worker_b" and r["kind"] == "work"
        )
        self.assertEqual(
            worker_b["payload"]["sources"],
            [{"title": "Fact page", "url": "https://example.com/fact"}],
        )
        # ...but nothing is cited: no Sources section, empty citations.
        self.assertNotIn("## Sources", result.deliverable)
        self.assertNotIn("https://example.com/fact", result.deliverable)
        self.assertEqual(result.chain.receipts[-1]["payload"]["citations"], [])
        # The verdict itself is recorded in the screen receipt.
        screen = self._screen_receipt(result)
        self.assertIs(
            screen["payload"]["screen"]["worker_b"]["evidence_sufficient"], False
        )

    def test_insufficient_verdict_suppresses_on_adjudication_path(self):
        transport = FakeTransport(
            verify_b=json.dumps({"verdict": "disagree", "issues": ["A is wrong"]}),
            screen_json=SCREEN_INSUFFICIENT,
        )
        result = crew_mod.run_crew(
            "the task", transport, test_config(), tavily_client=FakeTavily()
        )
        self.assertTrue(result.adjudicated)
        self.assertEqual(result.deliverable, "ADJUDICATED FINAL")
        self.assertNotIn("## Sources", result.deliverable)
        self.assertEqual(result.chain.receipts[-1]["payload"]["citations"], [])
        # The adjudicator is not handed the off-point list to cite.
        adjudicate_prompts = [
            user for _, system, user in transport.calls
            if system == crew_mod.ADJUDICATE_SYSTEM
        ]
        self.assertFalse(
            any("https://example.com/fact" in p for p in adjudicate_prompts)
        )

    def test_sufficient_verdict_keeps_sources_and_citations(self):
        transport = FakeTransport(screen_json=SCREEN_SUFFICIENT)
        result = crew_mod.run_crew(
            "the task", transport, test_config(), tavily_client=FakeTavily()
        )
        self.assertIn("## Sources", result.deliverable)
        self.assertIn("[Fact page](https://example.com/fact)", result.deliverable)
        self.assertEqual(
            result.chain.receipts[-1]["payload"]["citations"],
            ["https://example.com/fact"],
        )
        screen = self._screen_receipt(result)
        self.assertIs(
            screen["payload"]["screen"]["worker_b"]["evidence_sufficient"], True
        )

    def test_absent_field_keeps_legacy_behavior(self):
        # SCREEN_JSON (the default fixture) carries no evidence_sufficient
        # field at all — legacy screens and recorded runs behave as today.
        transport = FakeTransport()
        result = crew_mod.run_crew(
            "the task", transport, test_config(), tavily_client=FakeTavily()
        )
        self.assertIn("## Sources", result.deliverable)
        self.assertEqual(
            result.chain.receipts[-1]["payload"]["citations"],
            ["https://example.com/fact"],
        )
        screen = self._screen_receipt(result)
        self.assertNotIn(
            "evidence_sufficient", screen["payload"]["screen"]["worker_b"]
        )


if __name__ == "__main__":
    unittest.main()
