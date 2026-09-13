# Test fixture correction

The production code now correctly requires `entry_timestamp` for chronology-safe
summary calculations.

The failing unit test still used old fixture rows without `entry_timestamp`.
This bundle only updates that test fixture. No strategy, research, threshold,
entry, stop, trailing, or exit logic changes.

Replace:

tests/test_midpoint_v3_2_frozen_exit_validation_v1.py

Then rerun the 17-test suite.
