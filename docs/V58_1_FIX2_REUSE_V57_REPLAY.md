# V58.1 FIX2

The first V58.1 patch assumed an exact CANON constant line that differs in the
current repository, so it stopped without changing the file.

FIX2 inserts the V57 path using a tolerant regex over the V55/V52/CANON path
constants, with a pathlib-import fallback, then replaces only the local
`replay_session` implementation.

V58 accounting remains unchanged. Only the replay source is unified with the
already parity-proven V57 replay.
