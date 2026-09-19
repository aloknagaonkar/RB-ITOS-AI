# Historical OI Card Validation V1

Adds field-level validation to Historical OI Research without inventing missing data.

States: AVAILABLE, DERIVED, SOURCE_MISSING, INCONSISTENT.

Exact derived values include session imbalance, session percentages when baseline exists, baseline/current PCR, and PCR change. Canonical compact rows may remain SOURCE_MISSING for fixed baseline/current OI and exact fixed strikes; newly built V1.3 rows should expose those fields after rebuild.
