# Coordinated warmup-prevention compatibility proposal

This after-hours tool prepares the exact four-file change which the original warmup patch omitted: the reviewed operational cache writer, reference package runtime manifest, CLI EXPECTED_MANIFEST and companion CLI_SHA. It verifies original bindings and every listed package/runtime source, preserves all other pins, and asserts AST equality outside _write_cache. The proposed writer is the exact SHA validated by the prior 18-case repair/prevention VM run. Those tests are not reexecuted here; six binding regression tests run on VM, followed by the actual candidate CLI check against a disposable candidate source overlay.

Current rollout status is checked before and after, outside any held maintenance lock. The current plan's direct file-binding impact is listed. Original source bytes and proposed files are retained in a new private review folder. A proposal and SHA are produced. The existing plan is NOT edited, and no new approval or validation receipt is fabricated for it.

No apply command is implemented. The next deployment must include a successor rollout binding/rollback plan, quiescent installation of the whole compatibility chain, controlled consumer reload and post-reload health/warmup verification. It must also account for any existing immutable review references, not just directly listed current-plan bindings. Services listed in the proposal are a review set, not a claim that every one imports the writer.

No broker requests, credential reads, app database writes, source replacement, service control, controller resume, cache overwrite or key creation. Runtime status performs its existing read-only health/database checks. Only new private candidate/audit files are written. Candidate CLI check is a source-integrity check, not a substitute for service startup validation.

Independent WebSocket validation remains deferred to an open trading session using hilega-quote-stream-batch-v2. This proposal does not deploy warmup prevention or enable execution.

Local checks: syntax, AST parsing, packaged file digests and ZIP integrity only. Behavioral tests execute on the VM.
