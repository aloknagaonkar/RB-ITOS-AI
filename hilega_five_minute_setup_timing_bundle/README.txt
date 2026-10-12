Install on the latest alignment dual-exit adapter after audit fixes:
python hilega_five_minute_setup_timing_bundle/install.py
./scripts/restart.sh
Strategy ID unchanged; version five-minute-setup-1.1.0. New setups only at completed five-minute boundaries. Pending signal confirmation checks every completed minute for the existing ten-minute window. Entry occurs immediately on confirmation. No new pending checks after entry. Active and idle decision audit checkpoints are five-minute boundaries; minute quotes and internal prior-minute evidence remain updated. Dual exit, cutoff, sizing, Sandbox five legs and control arm unchanged. Dynamic replay cache signature changes automatically; existing saved reports are not rewritten. Restart does not arm a new Sandbox session.
