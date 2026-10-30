"""Offline evidence-tape replay; no broker, no original audit mutation."""
from __future__ import annotations
import argparse
from datetime import date
import json
from pathlib import Path
from .hilega_market_evidence_v1 import PlaybackHilegaSourcesV1
from .hilega_milega_live_shadow_v1 import HilegaMilegaLiveShadowCoordinatorV1


def main(argv=None):
    p=argparse.ArgumentParser(description="Replay captured Hilega source responses without broker access")
    p.add_argument("--journal", required=True, type=Path)
    p.add_argument("--expiry", required=True, type=date.fromisoformat)
    p.add_argument("--output-root", required=True, type=Path)
    a=p.parse_args(argv)
    if a.output_root.exists() and any(a.output_root.iterdir()):
        p.error("OUTPUT_ROOT_NOT_EMPTY: use a fresh directory")
    a.output_root.mkdir(parents=True, exist_ok=True)
    sources=PlaybackHilegaSourcesV1(a.journal)
    import hashlib
    from . import hilega_milega_strategy_v1 as strategy_module
    from . import hilega_milega_live_shadow_v1 as coordinator_module
    required={
        "strategy_source_sha256":hashlib.sha256(Path(strategy_module.__file__).read_bytes()).hexdigest(),
        "coordinator_source_sha256":hashlib.sha256(Path(coordinator_module.__file__).read_bytes()).hexdigest(),
    }
    coordinator=None
    ticks=0
    try:
        while True:
            now=sources.next_tick()
            if now is None:
                break
            if sources.process_start is not None:
                meta=sources.process_start
                if meta.get("expiry") != a.expiry.isoformat():
                    raise ValueError("RECORDED_EXPIRY_DIFFERS_FROM_REQUEST")
                if any(meta.get(k)!=v for k,v in required.items()):
                    raise ValueError("RECORDED_BUILD_SOURCE_SHA256_DIFFERENCE")
                coordinator=HilegaMilegaLiveShadowCoordinatorV1(
                    market_sources=sources, option_expiry=a.expiry,
                    step_audit_path=a.output_root/"step-audit.jsonl",
                    health_path=a.output_root/"data-health.jsonl",
                    cache_root=a.output_root/"warmup-cache-unused",
                )
            if coordinator is None:
                raise ValueError("RECORDED_PROCESS_START_MISSING")
            coordinator.process(now)
            ticks+=1
        sources.assert_consumed()
        if coordinator is None:
            raise ValueError("EMPTY_EVIDENCE_OR_NO_TICKS")
        ok, issue=coordinator.step_audit.verify_chain()
        status="REPLAYED" if ok else "AUDIT_CHAIN_FAILED"
        report={"status":status,"ticks":ticks,"audit_chain_ok":ok,
                "audit_chain_issue":issue,"observation_only":True,
                "execution_enabled":False,"paper_order_enabled":False,
                "note":"This verifies same-input processing, not historical/live semantic parity on its own."}
        (a.output_root/"evidence-replay-summary.json").write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps(report,indent=2))
        return 0 if ok else 2
    except Exception as exc:
        report={"status":"UNAVAILABLE", "reason":str(exc), "error_type":type(exc).__name__}
        (a.output_root/"evidence-replay-unavailable.json").write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps(report,indent=2))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
