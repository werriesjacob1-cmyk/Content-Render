#!/usr/bin/env python3
"""Zero-network regression tests for research_grounding.py."""\nimport os\nimport sys\nsys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n
from research_grounding import (
    EvidenceSource,
    GroqCompoundMiniProvider,
    ResearchBundle,
    YouAnswerProvider,
    parse_compound_response,
    parse_you_answer,
    research_with_fallback,
)


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_you_answer_grounding():
    payload = {
        "answer": (
            "Auroras are driven by charged particles from the Sun. [[1]] "
            "Those particles collide with oxygen and nitrogen in the atmosphere. [[1, 2]]"
        ),
        "citations": [
            {
                "source": "https://science.nasa.gov/example",
                "excerpts": ["Solar particles interact with Earth's upper atmosphere."],
            },
            {
                "source": "https://www.noaa.gov/example",
                "excerpts": ["Auroral emissions involve atmospheric oxygen and nitrogen."],
            },
        ],
        "results": {
            "web": [
                {
                    "url": "https://science.nasa.gov/example",
                    "title": "NASA Aurora",
                    "page_age": "2026-08-01T00:00:00",
                }
            ]
        },
    }
    bundle = parse_you_answer(payload, "what causes auroras?")
    check(bundle.grounded, "You response with inline citations + excerpts is grounded")
    check(len(bundle.load_bearing_claims()) == 2, "both citation-bound answer blocks become load-bearing")
    check(bundle.sources[0].title == "NASA Aurora", "web metadata enriches cited source")
    check(bundle.sources[0].published_at.startswith("2026-08-01"), "page age is preserved")


def test_you_answer_malformed_index_does_not_shift():
    payload = {
        "answer": "The supported statement is here. [[2]]",
        "citations": [
            {"source": "", "excerpts": []},
            {
                "source": "https://www.usgs.gov/example",
                "excerpts": ["The supported statement is here."],
            },
        ],
    }
    bundle = parse_you_answer(payload, "test")
    check(bundle.grounded, "citation #2 remains mapped to original second source")
    claim = bundle.load_bearing_claims()[0]
    check(claim.source_ids == (bundle.sources[1].source_id,), "invalid citation #1 does not collapse numbering")


def test_you_answer_missing_excerpts_fails_closed():
    payload = {
        "answer": "A plausible statement. [[1]]",
        "citations": [{"source": "https://example.com/source", "excerpts": []}],
    }
    bundle = parse_you_answer(payload, "test")
    check(not bundle.grounded, "citation URL without supporting excerpts is not load-bearing")
    check(not bundle.load_bearing_claims(), "no load-bearing claims leak through")


def test_compound_requires_executed_tools():
    payload = {
        "choices": [{
            "message": {
                "content": "According to NASA, this is true. https://nasa.gov/fake-looking-citation"
            }
        }]
    }
    bundle = parse_compound_response(payload, "test")
    check(not bundle.grounded, "citation-looking prose without executed_tools is rejected")
    check(not bundle.raw_tool_evidence_present, "missing tool evidence is recorded")
    check(not bundle.load_bearing_claims(), "Compound prose is never auto-promoted to claims")


def test_compound_tool_evidence_is_review_only():
    payload = {
        "choices": [{
            "message": {
                "content": "A compact researched answer.",
                "executed_tools": [{
                    "type": "search",
                    "results": [{
                        "url": "https://science.nasa.gov/example",
                        "title": "NASA source",
                        "snippet": "Observed evidence from NASA.",
                    }],
                }],
            }
        }]
    }
    bundle = parse_compound_response(payload, "test")
    check(bundle.raw_tool_evidence_present, "executed_tools presence is captured")
    check(bundle.grounded, "inspectable executed tool source is recognized as grounded-for-review")
    check(len(bundle.sources) == 1 and bundle.sources[0].is_verifiable(), "tool source has URL + evidence text")
    check(not bundle.load_bearing_claims(), "Compound still emits no load-bearing claims without exact span binding")


def test_provider_input_guards():
    you = YouAnswerProvider(api_key="x")
    try:
        you.research("x" * 401)
        raise AssertionError("long query should fail")
    except ValueError:
        pass
    check(True, "You query length cap enforced before network")

    try:
        you.research("aurora", include_domains=["nasa.gov"], boost_domains=["noaa.gov"])
        raise AssertionError("mutually exclusive source controls should fail")
    except ValueError:
        pass
    check(True, "You incompatible domain controls rejected")

    groq = GroqCompoundMiniProvider(api_key="")
    try:
        groq.research("aurora")
        raise AssertionError("missing key should fail")
    except Exception as e:
        check("GROQ_API_KEY" in str(e), "Compound missing-key error is explicit")


class FakeProvider:
    def __init__(self, result, name):
        self._result = result
        self.name = name
    def available(self):
        return True
    def research(self, query):
        return self._result


def test_fallback_never_returns_ungrounded():
    weak = ResearchBundle(
        provider="weak",
        query="q",
        answer="sounds convincing",
        claims=(),
        sources=(),
        grounded=False,
        grounding_reason="no evidence",
    )
    good_source = EvidenceSource(
        source_id="src_ok",
        url="https://nasa.gov/x",
        excerpts=("supporting excerpt",),
        provider="fake",
    )
    # A provider can be grounded-for-review while still having no load-bearing claims;
    # research_with_fallback must not stop there.
    review_only = ResearchBundle(
        provider="review",
        query="q",
        answer="review only",
        claims=(),
        sources=(good_source,),
        grounded=True,
        grounding_reason="tool evidence only",
        raw_tool_evidence_present=True,
    )
    check(research_with_fallback("q", [FakeProvider(weak, "weak")]) is None,
          "ungrounded provider result never silently accepted")
    got = research_with_fallback("q", [FakeProvider(weak, "weak"), FakeProvider(review_only, "review")])
    check(got is None, "review-only tool evidence cannot silently become story facts")
    got_review = research_with_fallback(
        "q", [FakeProvider(review_only, "review")], allow_review_only=True
    )
    check(got_review is review_only, "review-only evidence requires explicit opt-in")


if __name__ == "__main__":
    test_you_answer_grounding()
    test_you_answer_malformed_index_does_not_shift()
    test_you_answer_missing_excerpts_fails_closed()
    test_compound_requires_executed_tools()
    test_compound_tool_evidence_is_review_only()
    test_provider_input_guards()
    test_fallback_never_returns_ungrounded()
    print("research_grounding tests: PASS")
