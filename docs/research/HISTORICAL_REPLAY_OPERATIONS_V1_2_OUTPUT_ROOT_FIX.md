# Historical Replay Operations V1.2 Output Root Fix

The V1.2 runner intentionally defaulted to:

`data/live-observation/replay-v1-2`

for isolated parity testing.

After Replay Operations was switched to V1.2, the worker inherited that default.
That means a successful UI/API replay would not update the canonical replay
directory consumed by the existing Historical Replay API/UI.

This patch keeps the V1.2 optimized runner but makes the Operations worker pass:

`output_root="data/live-observation/replay"`

explicitly.

The standalone V1.2 CLI still defaults to its isolated `replay-v1-2` directory,
which is useful for future parity tests.
