# V58.1 — Reuse V57 parity-proven replay

V57 already passed exact frozen ownership parity across all four historical blocks.

V58.1 removes replay-path drift by making V58 call V57's existing
`replay_session` implementation and leaving V58 responsible only for accounting.

No B/E entry rule, Candidate A rule, VWAP threshold, CAP20 rule, re-entry rule,
or structural-terminal rule is changed.
