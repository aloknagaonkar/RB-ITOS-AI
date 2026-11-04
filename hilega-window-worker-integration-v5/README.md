# Native transaction checkpoint guard validation v5

Installs a checkpoint callback before worker dispatch on opted-in disabled windows. It preserves the existing callback, then checks guard identity, lease, deadline and pause intent at BEFORE_TRANSACTION, AFTER_PLAN_INSERT, AFTER_ADAPTER_REQUEST_INSERT and BEFORE_COMMIT. Failure raises through the native transaction context, causing its existing rollback and pause path. No monkeypatch of database commit or production gate is used in candidate runtime.

VM batch: five previous scenarios plus guard SIGKILL after plan insert, after adapter request insert and before commit. Disposable fixture injection waits for observed guard death. Each fault case requires zero application preparation/binding/reservation rows, zero adapter requests/attempts/receipts and no boundary receipt.

Scope limitation: this is validation at native checkpoints, NOT atomic guard liveness with SQLite commit. A final instruction gap remains after the last check. No live deployment, window arming or activation is available. Startup wrapper and live recovery qualification remain pending. Prior eight enrollment tests are not rerun. Behavioral tests run only on VM.

Reminders: open-session quote-stream v4 and contract coverage; broker timestamp clarification and final November 2 note/fees; real disabled seed/owner enrollment and separate final activation.
