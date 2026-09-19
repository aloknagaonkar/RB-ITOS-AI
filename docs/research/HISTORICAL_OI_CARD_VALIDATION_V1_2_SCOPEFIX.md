# Historical OI Card Validation V1.2 Scope Fix

Root cause: the prior validation patch updated JSX to reference validation and
derived fixed-basket variables, but those declarations were not inserted into
the `Audit()` component scope.

V1.2 locates `function Audit({row}:{row:Row})` with a regex, injects all required
local declarations immediately after the opening brace, and performs a post-apply
verification before reporting success.

No strategy or calculation methodology changes.
