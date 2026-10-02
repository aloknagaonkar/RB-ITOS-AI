#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend/market_lab/upstox_live_shadow_sources_v1.py"
WORKER = ROOT / "backend/market_lab/live_shadow_worker_v1.py"


def patch_source(text: str) -> str:
    if "def nifty_futures_intraday_1m(" in text:
        return text

    anchor = '''    def nifty_intraday_1m(self,*,now:datetime|None=None):
        local=(now or datetime.now(IST)).astimezone(IST);instrument_key="NSE_INDEX|Nifty 50"
        encoded=quote(instrument_key,safe="")
        body=self.gateway._get(f"/v3/historical-candle/intraday/{encoded}/minutes/1")
        return normalize_upstox_historical_candles(instrument_key,local.date(),body)
'''
    if text.count(anchor) != 1:
        raise SystemExit(
            "STOP: exact nifty_intraday_1m source anchor not found once; repo changed."
        )

    addition = anchor + '''
    def nifty_futures_intraday_1m(self,*,now:datetime|None=None):
        local=(now or datetime.now(IST)).astimezone(IST)
        instrument=self.gateway.resolve_nifty_front_future(today=local.date())
        encoded=quote(instrument.instrument_key,safe="")
        body=self.gateway._get(f"/v3/historical-candle/intraday/{encoded}/minutes/1")
        return normalize_upstox_historical_candles(instrument.instrument_key,local.date(),body)
'''
    return text.replace(anchor, addition, 1)


def patch_worker(text: str) -> str:
    import_anchor = '''from .hilega_directional_live_shadow_v1 import (
    STRATEGY_ID as HILEGA_DIRECTIONAL_STRATEGY_ID,
    HilegaDirectionalLiveShadowCoordinatorV1,
)
'''
    if "from .midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1" not in text:
        if text.count(import_anchor) != 1:
            raise SystemExit("STOP: worker import anchor not found exactly once")
        text = text.replace(
            import_anchor,
            import_anchor + "from .midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1\n",
            1,
        )

    hilega_ctor = "            coord=HilegaMilegaLiveShadowCoordinatorV1(market_sources=active_sources,option_expiry=option_expiry)\n"
    hilega_aux = hilega_ctor + '            midpoint_coord=MidpointLiveShadowCoordinatorV1(market_sources=sources) if os.getenv("MIDPOINT_SHADOW_ENABLED","0")=="1" else None\n'
    if text.count("midpoint_coord=MidpointLiveShadowCoordinatorV1") == 0:
        if text.count(hilega_ctor) != 1:
            raise SystemExit("STOP: Hilega coordinator constructor anchor not found exactly once")
        text = text.replace(hilega_ctor, hilega_aux, 1)

    directional_ctor = "            coord=HilegaDirectionalLiveShadowCoordinatorV1(market_sources=active_sources,option_expiry=option_expiry)\n"
    directional_aux = directional_ctor + '            midpoint_coord=MidpointLiveShadowCoordinatorV1(market_sources=sources) if os.getenv("MIDPOINT_SHADOW_ENABLED","0")=="1" else None\n'
    if text.count("midpoint_coord=MidpointLiveShadowCoordinatorV1") == 1:
        if text.count(directional_ctor) != 1:
            raise SystemExit("STOP: directional coordinator constructor anchor not found exactly once")
        text = text.replace(directional_ctor, directional_aux, 1)

    target = "                        coord.process(now)\n"
    replacement = (
        "                        coord.process(now)\n"
        "                        if midpoint_coord is not None:\n"
        "                            midpoint_coord.process(now)\n"
    )
    aux_calls = text.count("midpoint_coord.process(now)")
    if aux_calls == 0:
        if text.count(target) != 2:
            raise SystemExit(
                f"STOP: expected exactly two Hilega coord.process(now) anchors, found {text.count(target)}"
            )
        text = text.replace(target, replacement, 2)
    elif aux_calls != 2:
        raise SystemExit(f"STOP: partial Midpoint worker patch detected: {aux_calls}")

    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    for p in (SOURCE, WORKER):
        if not p.exists():
            raise SystemExit(f"STOP: missing {p}")

    source_old = SOURCE.read_text()
    worker_old = WORKER.read_text()
    source_new = patch_source(source_old)
    worker_new = patch_worker(worker_old)

    print("MIDPOINT M3B SHARED SOURCE / WORKER PATCH")
    print("=" * 88)
    print(f"source changed={source_new != source_old}")
    print(f"worker changed={worker_new != worker_old}")
    print("MIDPOINT_SHADOW_ENABLED default=0")
    print("No process is started or restarted by this script.")

    if not args.apply:
        print("DRY RUN ONLY. Re-run with --apply only after tests/review.")
        return

    for p in (SOURCE, WORKER):
        backup = p.with_suffix(p.suffix + ".pre-midpoint-m3b.bak")
        if not backup.exists():
            shutil.copy2(p, backup)

    SOURCE.write_text(source_new)
    WORKER.write_text(worker_new)
    print("APPLIED")
    print("Midpoint remains disabled until MIDPOINT_SHADOW_ENABLED=1.")


if __name__ == "__main__":
    main()
