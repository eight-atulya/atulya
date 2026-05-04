# Local LLM Background Pipelines Need Operation-Specific Limits And Failure-Aware Batch Fallbacks

Date: 2026-05-03
Repo: atulya
Area: local llm, retain, consolidation, async operations, timeout resilience

## Trigger

Two local-LLM incidents looked similar from the surface:

- long retain jobs timed out while processing large documents
- observation consolidation timed out during background processing

Both showed repeated `APIConnectionError ... Request timed out` warnings, which made it tempting to blame the provider or retry settings alone.

## Root Cause

The real issue was not one generic timeout bug.

It was a repeated systems pattern:

- operation-specific concurrency settings existed in config but were not always enforced in the hot path
- some local-LLM flows still built request shapes that were too large for a slower local model
- failure handling could be too forgiving, allowing work to look "done" when the real LLM step had not completed successfully

The retain path and consolidation path failed for different immediate reasons:

- retain was fanning out chunk extraction in parallel and not correctly using the retain-specific timeout/config wiring
- consolidation already had timeout config, but its recall fanout ignored the consolidation-specific concurrency limit and its failed LLM batches could fall through in a way that risked silently advancing `consolidated_at`

## Practical Pattern

When a local-LLM background workflow starts timing out, use this sequence:

1. confirm whether the path is truly parallelizing work, and where
2. verify the operation-specific timeout and concurrency env vars are actually wired into the runtime object used by that path
3. enforce operation-local semaphores in the real hot path, even if a global LLM semaphore also exists
4. prefer known-size controls first, such as smaller chunk or batch sizes
5. when an LLM batch still fails, split the batch and retry smaller units before marking the parent work complete
6. never let a failed LLM step silently advance durable completion markers

## Better Design Rule

For local models, "global max concurrency" is not enough as the only defense.

Use layered control:

- global semaphore for whole-process backpressure
- operation-specific semaphore for the subsystem that is actually fanning out
- operation-specific timeout with explicit fallback to the global timeout
- operation-specific batch size or chunk size as the first efficiency knob
- recursive or staged batch shrinking only on hard failure

This keeps the normal fast path simple while making slow local providers survivable.

## Publish-Safe Validation Rule

When fixing this class of issue, validation should prove three separate things:

- the operation-specific config is loaded and reaches the provider wrapper
- the concurrency limit is actually respected in the targeted path
- failed large batches no longer get treated as successful completion

Targeted unit tests are a better first proof than waiting on a full live local-model run, but the original real path should still be spot-checked afterward.

## Failure Modes To Avoid

- assuming a documented env var is already active in code
- relying on the global semaphore alone when a subsystem creates many subcalls
- treating timeout retries as success handling
- swallowing exhausted LLM batch failures and then stamping progress markers anyway
- making the fallback strategy so complex that the healthy path slows down

## Expected Benefits

- local LM Studio and Ollama setups degrade more gracefully on long jobs
- long retains and consolidation jobs become tunable without code changes
- async progress and durable state stay honest under failure
- future agents can diagnose "same symptom, different path" incidents faster

## Cortex Links

- Related publish protocol: [full_stack_feature_rollout_and_batch_publish](../../03_systems/03_workflows/10_software_engineering_workflow/brain_protocols/full_stack_feature_rollout_and_batch_publish/BRAIN.md)
- Related root contract: [BRAIN.md](../../../../../BRAIN.md)
