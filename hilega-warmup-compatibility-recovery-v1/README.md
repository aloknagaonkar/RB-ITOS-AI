# Warmup compatibility recovery

Restores ONLY the exact original application cache writer from the verified repair backup. Retains the verified repaired Oct 30 cache. Does NOT change package manifests, CLI pins, service source, current plan, registration or immutable production release. Requires stopped companion, paused controller, empty lifecycle baseline and exact pinned release. Uses the existing maintenance lock, backs up the modified writer, verifies package check, starts only the lifecycle companion and verifies current rollout status. No controller resume or live activation.

Run recover.py --repo "$PWD" --apply. Without --apply it checks prerequisites only. If any step fails, inspect the newly created private audit; do not retry blindly. Source rollback can already have occurred when a later check fails. Service start may already have occurred before status verification fails. No automatic data rollback.

This rolls back the on-disk prevention patch; prevention is NOT complete. Existing readers still reject incomplete warmup sessions, but complete-write prevention requires a coordinated deployment with matching dependency bindings. Existing processes are not reloaded except starting the failed companion. No guarantee is made about versions already loaded in other processes. Broker data availability cannot be guaranteed.

Local validation: static syntax and ZIP checks only. Actual package and rollout checks run on the VM.
