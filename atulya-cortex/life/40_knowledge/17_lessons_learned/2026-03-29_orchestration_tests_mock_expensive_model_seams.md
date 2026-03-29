# Orchestration Tests Should Mock Expensive Model Seams

Date: 2026-03-29
Repo: atulya
Area: dream generation, async reflect, API contract testing

## Trigger

Dream and async reflect tests were intermittently slow or timing out because they booted heavyweight local model dependencies during fixture setup, even when the behavior under test was orchestration logic rather than provider correctness.

## Root Cause

Several tests used the generic `memory` or `memory_no_llm_verify` fixtures, which still pulled in real embeddings and reranker initialization from `tests/conftest.py`. That meant:

- `sentence-transformers` and `transformers` imports could dominate runtime
- local model availability leaked into tests that should be cloud-safe
- failures appeared as infrastructure/setup timeouts instead of true logic regressions

## Better System Design

For orchestration and contract tests:

- keep the real `MemoryEngine`
- keep the real database path
- keep the real API / async operation path
- replace embeddings and reranker with tiny deterministic doubles
- mock the LLM-facing seam directly with `set_mock_response()` / `set_mock_exception()` or a patched engine method

For provider-contract tests:

- keep the real provider setup only when the test is explicitly about provider behavior, structured output support, token accounting, or tool-calling compliance

## Applied Pattern

This was applied to:

- `tests/test_dreaming.py`
- `tests/test_async_reflect.py`
- `tests/test_reflect_empty_based_on.py`

These tests now verify the real orchestration path without depending on heavyweight model boot.

## Practical Rule

If a test asks "did the engine / API / worker wire this correctly?", mock the expensive model seam.

If a test asks "does this model/provider actually behave correctly?", keep the real provider path.

## Expected Benefits

- stable CI and cloud execution
- less dependence on local model state
- faster feedback on logic changes
- failures that point to the real broken layer
