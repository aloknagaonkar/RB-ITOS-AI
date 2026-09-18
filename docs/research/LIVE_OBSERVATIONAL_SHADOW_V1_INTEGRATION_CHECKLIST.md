# Integration checklist

- [ ] Identify existing live ALL_3 producer.
- [ ] Confirm ALL_3 uses completed 5-minute candles only.
- [ ] Reuse existing futures OI state mapping; do not reimplement it here.
- [ ] Reuse exact moving-ATM resolver.
- [ ] Exact option instrument key available.
- [ ] Exact next-minute option open available.
- [ ] Completed 1-minute option OHLC available.
- [ ] Asia/Kolkata offsets retained in stored timestamps.
- [ ] Add duplicate-observation prevention in runtime adapter.
- [ ] Missing exact data -> `incomplete()`/`reject()`, never fallback.
- [ ] No broker/order dependency imported.
- [ ] JSONL path stored on durable disk and backed up.
- [ ] Run hash-chain verify after market close.
- [ ] Generate ledger and daily summary after market close.
- [ ] Freeze observation rules during prospective collection.
