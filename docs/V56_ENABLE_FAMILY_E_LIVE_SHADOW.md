# V56 live-shadow behavior

At each confirmed boundary close the coordinator emits `BOUNDARY_CLASSIFIED`.

B owner:
- starts existing B delayed watch

E owner:
- immediate shadow entry when Family E is enabled
- blocked if another reference is active
- uses the same shared V54 management lifecycle

OTHER_FRESH_A:
- audit only
- neither B nor E claims the event

Family E is enabled only for observation-only shadow.
No execution, paper order, or quantity is enabled.
