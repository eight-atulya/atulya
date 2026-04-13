# Public GitHub Codebase Imports Should Accept Repo URLs And Pending Cancel Should Clean Up Snapshot State

## Summary

Codebase import ergonomics improved when the system accepted a pasted public GitHub repository URL and normalized it into the existing archive-based import pipeline, instead of forcing operators to split owner, repo, and ref manually.

At the same time, queued operation cancellation needed to be stricter and more state-aware:

- only `pending` operations should be cancellable
- completed or failed operations should remain durable history
- canceling a queued codebase import or refresh should remove its staged snapshot state so the bank is not left with orphaned pending codebase records

## What Happened

The immediate trigger was a production-like failure in public GitHub codebase import:

- the GitHub archive request hit a `302 Found`
- the worker retried instead of consuming the redirected archive
- the UI also still made operators enter `owner`, `repo`, and `ref` manually even when they already had a GitHub URL

That surfaced a second design issue:

- the generic cancel path could remove queued work from `async_operations`
- but queued codebase imports had already created `codebases` and `codebase_snapshots` rows
- cancellation without cleanup would leave behind empty pending codebase state

## Decision

Keep public GitHub import archive-based by default, but make it easier to use:

- follow redirects explicitly on the streamed `zipball` request
- accept a `repo_url` in the API
- let the UI parse and prefill a pasted GitHub URL

Do not switch the default public import path to `git clone`.

For cancellation:

- allow cancel only while the job is still `pending`
- reject cancellation once a job is `processing`, `completed`, or `failed`
- for queued codebase imports and refreshes, delete the pending snapshot and delete the codebase too when that canceled snapshot was its only staged state

## Why This Was Better

This kept the original v1 system design intact:

- no persistent checkout state
- no credential or cleanup burden for public imports
- deterministic archive-based ingestion remains the default
- better developer UX without increasing operational complexity

It also made cancellation honest rather than cosmetic:

- the queue entry disappears
- staged codebase metadata does not linger in a broken intermediate state
- operation history remains trustworthy because completed work can no longer be retroactively "cancelled"

## Validation

Validated with:

- focused codebase import tests for redirect handling
- HTTP coverage for `repo_url`-based GitHub import
- cancellation tests for completed-operation rejection
- cancellation tests for queued codebase snapshot cleanup
- repo lint

## Reusable Rule

When an async feature creates reviewable state before execution completes:

1. keep the user-facing input path ergonomic
2. preserve the cheapest correct execution path underneath
3. make cancellation pending-only
4. clean up any pre-created state that would otherwise survive a canceled queue item
