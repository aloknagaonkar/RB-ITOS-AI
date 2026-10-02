from sqlalchemy import select
from sqlalchemy.orm import Session
from market_lab.domain import IST, Snapshot
from market_lab.live_fixed_session_anchor_recovery_v1 import LiveFixedSessionAnchorManagerV1
from market_lab.storage import Configuration, Observation, make_engine
engine=make_engine()
with Session(engine) as s:
    cfg=s.scalar(select(Configuration).order_by(Configuration.id.desc()))
    if cfg is None: raise SystemExit("No configuration")
    row=s.scalar(select(Observation).where(Observation.config_id==cfg.id).order_by(Observation.id.desc()))
    if row is None: raise SystemExit("No observation")
snap=Snapshot.model_validate(row.snapshot); t=snap.received_at.astimezone(IST); cp=t.replace(minute=(t.minute//5)*5,second=0,microsecond=0)
mgr=LiveFixedSessionAnchorManagerV1(engine=engine,config_id=cfg.id); a=mgr.ensure(cp); m=mgr.metrics(snap,cp)
print("anchor_status:",a.status); print("provenance:",a.provenance); print("checkpoint_time:",a.checkpoint_time); print("source_candle_time:",a.source_candle_time); print("source_semantics:",a.source_semantics); print("spot:",a.spot); print("atm:",a.atm); print("strikes:",list(a.strikes)); print("contract_count:",len(a.legs)); print("ce_total:",a.ce_total); print("pe_total:",a.pe_total); print("fixed_pcr:",a.fixed_pcr); print("fallback_used:",a.fallback_used); print("issue:",a.issue)
print("fixed_session:",m.payload() if m else "INCOMPLETE")
