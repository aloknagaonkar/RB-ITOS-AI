# Root cause

The failure:

```text
ValueError: entry_timestamp missing
```

is not caused by the regime diagnostic itself.

The regime diagnostic correctly requires exact entry time for time-of-day,
month, weekday, and chronology-safe diagnostics.

The source JSON lacked `entry_timestamp` because the prior chronology package
contained instructions/helper code but did not automatically modify the
already-existing exit-management module in the user's repository.

This bundle supplies complete corrected source files.

No strategy thresholds, entry rules, exit rules, or OOS usage are changed.
