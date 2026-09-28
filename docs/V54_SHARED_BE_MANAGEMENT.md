# V54 — Shared B/E post-entry management

V54 does not enable Family E in the live coordinator.

It makes the existing Family-B lifecycle family-aware so an E-qualified entry
can use exactly the same management methods.

B behavior remains unchanged:
- default family = B
- B entry explicitly stamps B
- B detector and 10-minute watch are untouched
- CAP20 and reentry logic are untouched

E:
- has an explicit start_e_entry() constructor
- requires mature directional VWAP at the boundary
- enters the same FamilyBShadowRuntime lifecycle object
- all later management methods are shared

Safety:
- family_e_enabled=False
- observation_only=True
- execution_enabled=False
- paper_order_enabled=False
- quantity=None

Do not restart live workers in V54.
V55 should own actual coordinator selection/live-shadow enablement.
