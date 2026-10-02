# Historical Replay Audit Responsive V1

Fixes the horizontal drag in Historical Replay audit details.

The existing decision-audit table had a forced minimum width, so Expected / Actual Evidence / Explanation extended beyond the visible replay panel. This patch keeps the whole replay and expanded audit inside the viewport, removes the forced decision-table minimum width, uses fixed table layout, assigns practical column percentages, and wraps long evidence/explanation text.

No strategy, candidate, replay, trade, or audit logic is changed.
