# RB-1.4.0 — Self-Learning Replay

Historical Decision Replay now classifies the quality of each historical decision after the outcome is known, without feeding future data into the original decision.

Verdicts:
- CORRECT_TAKE
- FALSE_POSITIVE
- MISSED_OPPORTUNITY
- CORRECT_SKIP
- INCORRECT_BLOCK
- CORRECT_BLOCK
- NEUTRAL / UNRESOLVED

Research Lab now displays Decision Accuracy, Missed Opportunities, False Positives, Correct Skips, per-signal Learning Attribution, and advisory Learning Recommendations.

Learning is research-only in RB-1.4.0. No live threshold, weight, execution, stop, target, sizing, lifecycle, queue, or committee setting is automatically changed.

Validation: 223 tests passed.
