# Historical OI Card Validation V1.1 TypeScript Fix

The V1 UI referenced validation/derived variables from `Audit()` but they were not actually declared in that component scope.

V1.1 declares:
- `movingChecks`
- `fixedChecks`
- `fixedCePct`
- `fixedPePct`
- `fixedImbalance`
- `fixedBasePcr`
- `fixedCurrentPcr`
- `fixedPcrChange`

No calculation rules are changed. This is a TypeScript scope fix only.
