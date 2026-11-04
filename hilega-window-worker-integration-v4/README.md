# Worker guard rejection candidate v4

Adds an opt-in pre-poll guard PID/start-time, ownership, deadline, lease and pause-intent check before the existing native worker dispatch. A dead or replaced guard causes native pause before dispatch. No config preserves the original default closed dispatch. Guard identity is recorded by the disposable arm adapter.

Runs the four previous disposable scenarios plus a fresh-signal case with a killed guard while recovery is held behind its lock. The worker itself must pause without creating a preparation. Candidate files remain private and sealed.

This reduces the confirmed exposure at the worker entry boundary. It does NOT establish atomic guard validity through the entire preparation transaction or prevent transient controller arming. Exact pre-resume/transaction races, live wrapper and recovery qualification, and installation remain blocked. No live apply available. No local behavioral tests run.

Pending reminders: open-session v4 quote validation and contract coverage; Upstox timestamp reply and final November 2 contract note/fees; real fresh disabled enrollment and separate final activation.
