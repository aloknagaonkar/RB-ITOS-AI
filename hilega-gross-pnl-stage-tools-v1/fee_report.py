"""Fixed GET-only aggregate charges capture. No trade fee or net-P&L authority."""
import argparse
from contextlib import closing
from datetime import datetime, date, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from signature_checks import sign, aware, day

MODEL="HILEGA_AGGREGATE_FEE_REPORT_CAPTURE_V1"
ENDPOINT="https://api.upstox.com/v2/trade/profit-loss/charges"
COMPONENTS=("brokerage","taxes.gst","taxes.stt","taxes.stamp_duty",
    "charges.transaction","charges.clearing","charges.ipft","charges.others",
    "charges.sebi_turnover","charges.demat_transaction")


def need(ok,reason):
    if not ok:raise ValueError(reason)


def query(session):
    need(isinstance(session,str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}",session),
         "SESSION_DATE_REQUIRED")
    value=date.fromisoformat(session)
    year=value.year if value.month>=4 else value.year-1
    return dict(from_date=value.strftime("%d-%m-%Y"),to_date=value.strftime("%d-%m-%Y"),
                segment="FO",financial_year=f"{year%100:02d}{(year+1)%100:02d}")


def paise(value):
    need(type(value) in (str,int,float,Decimal),"CHARGE_VALUE_INVALID")
    try:number=Decimal(str(value))
    except InvalidOperation:raise ValueError("CHARGE_VALUE_INVALID") from None
    need(number.is_finite() and number>=0,"CHARGE_VALUE_INVALID")
    scaled=number*100
    need(scaled==scaled.to_integral_value(),"FRACTIONAL_PAISE_REQUIRES_REVIEW")
    return int(scaled)


def assess_response(raw):
    need(isinstance(raw,dict) and raw.get("status")=="success","CHARGES_PROVIDER_NOT_SUCCESS")
    data=raw.get("data")
    need(isinstance(data,dict) and isinstance(data.get("charges_breakdown"),dict),
         "CHARGES_RESPONSE_SCHEMA_INVALID")
    charges=data["charges_breakdown"]
    need("total" in charges and charges["total"] is not None,"AGGREGATE_TOTAL_UNAVAILABLE")
    total=paise(charges["total"])
    missing=[];values={}
    for name in COMPONENTS:
        value=charges
        for part in name.split("."):
            value=value.get(part) if isinstance(value,dict) else None
        if value is None:missing.append(name)
        else:values[name]=paise(value)
    subtotal=sum(values.values())
    need(subtotal<=total,"COMPONENT_SUM_EXCEEDS_AGGREGATE_TOTAL")
    return dict(
        reported_aggregate_total_paise=total,
        missing_or_null_component_paths=missing,
        known_component_sum_paise=subtotal,
        component_arithmetic_matches_total=subtotal==total,
        scope="PROVIDER_ACCOUNT_FO_DATE_AGGREGATE_ONLY",
        per_order_fees_available=False,fees_complete=False,
        trade_fee_attribution_verified=False,
        provider_report_current_session_completeness_verified=False,
        provider_aggregation_finality_verified=False,
        strategy_ownership_verified=False,real_funds_reservation_verified=False,
        source_atomic=False,
        realized_net_pnl_paise=None,open_net_pnl_paise=None,
        risk_gate_input_ready=False,entry_permission=False,
        production_execution_enabled=False,production_ready=False)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("REPORT_REDIRECT_FORBIDDEN")


def unique_keys(pairs):
    result={}
    for key,value in pairs:
        need(key not in result,"DUPLICATE_REPORT_JSON_KEY")
        result[key]=value
    return result


class FixedChargesClient:
    def __init__(self,token):
        need(isinstance(token,str) and bool(token.strip()),"READ_TOKEN_MISSING")
        self.token=token.strip()

    def get(self,session):
        url=ENDPOINT+"?"+urlencode(query(session))
        request=Request(url,method="GET",headers={
            "Authorization":"Bearer "+self.token,"Accept":"application/json",
            "User-Agent":"RB-ITOS-AI/read-only-fee-report"})
        try:
            with build_opener(NoRedirect()).open(request,timeout=8) as response:
                raw=response.read(262145)
                need(response.status==200,"CHARGES_HTTP_STATUS_INVALID")
            need(len(raw)<=262144,"CHARGES_RESPONSE_TOO_LARGE")
            return json.loads(raw,parse_float=Decimal,object_pairs_hook=unique_keys)
        except ValueError as exc:
            message=str(exc)
            if re.fullmatch("[A-Z][A-Z0-9_]{0,100}",message):raise
            raise ValueError("CHARGES_RESPONSE_INVALID") from None
        except Exception:
            raise ValueError("CHARGES_GET_FAILED_NO_RETRY") from None


def collect_report(profile,charges,pin,*,matches,clock):
    """Internal orchestration; CLI supplies fixed installed/fixed GET clients."""
    start=aware(clock().isoformat())
    matches(profile.get("profile"),pin)
    raw=charges.get(day(start))
    assessed=assess_response(raw)
    matches(profile.get("profile"),pin)
    end=aware(clock().isoformat())
    need(0<=(end-start).total_seconds()<=30 and day(start)==day(end),
         "FEE_CAPTURE_SLOW_OR_SESSION_CHANGED")
    # Normalize Decimal for deterministic local signatures and private JSON.
    raw=json.loads(json.dumps(raw,default=lambda v:str(v) if isinstance(v,Decimal) else v))
    envelope=dict(model=MODEL,account_scope=pin["scope"],
        started_at=start.isoformat(),completed_at=end.isoformat(),
        session_date=day(start),query=query(day(start)),
        profile_verified_before_and_after=True,provider_response=raw,
        assessment=assessed,source_atomic=False,orders_sent=False,
        production_execution_enabled=False,entry_permission=False)
    envelope["signature"]=sign(envelope,pin)
    return envelope


def paused(root):
    path=root/"data/research/hilega-production-workspace/sim.sqlite"
    need(path.is_file() and not path.is_symlink(),"EXISTING_APPLICATION_DB_REQUIRED")
    for parent in path.parents:need(not parent.is_symlink(),"SYMLINK_PARENT_FORBIDDEN")
    with path.open("rb") as stream:header=stream.read(20)
    need(header[:16]==b"SQLite format 3\x00" and header[18:20]==b"\x01\x01",
         "ROLLBACK_JOURNAL_APPLICATION_REQUIRED")
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        control=json.loads(db.execute("SELECT data FROM control WHERE id=1").fetchone()[0])
        route=json.loads(db.execute("SELECT data FROM preparation_route WHERE id=1").fetchone()[0])
        need(control.get("mode")=="PAUSED","CONTROLLER_MUST_BE_PAUSED")
        need(route==dict(route="PREPARATION_ONLY",model="APPLICATION_PREPARATION_ROUTE_V1"),
             "PREPARATION_ROUTE_REQUIRED")
        db.rollback()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["check"])
    parser.add_argument("--capture-report",action="store_true",required=True)
    parser.add_argument("--repo",type=Path,default=Path.home()/"RB-ITOS-AI")
    parser.add_argument("--pin-file",type=Path,
                        default=Path.home()/"hilega-private/upstox-account-pin.json")
    args=parser.parse_args();root=args.repo.resolve()
    manifest=json.loads(Path(__file__).with_name("manifest.json").read_text())
    for name,expected in manifest["installed_source_sha256"].items():
        path=root/name
        need(path.is_file() and not path.is_symlink()
             and hashlib.sha256(path.read_bytes()).hexdigest()==expected,"INSTALLED_SOURCE_CHANGED")
    for name,expected in manifest["package_sha256"].items():
        need(hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()==expected,
             "PACKAGE_SOURCE_CHANGED")
    paused(root)
    sys.path.insert(0,str(root/"backend"))
    from market_lab.hilega_production_account_adapter_v1 import Client,read_pin,matches
    from dotenv import dotenv_values
    settings=dotenv_values(root/".env")
    def setting(name):
        shell,file=os.getenv(name),settings.get(name)
        need(not(shell and file and shell!=file),"TOKEN_CONFIGURATION_CONFLICT")
        return shell or file
    primary=setting("HILEGA_PRODUCTION_BROKER_READ_TOKEN")
    secondary=setting("UPSTOX_ACCESS_TOKEN")
    token=(primary or secondary or "").strip()
    need(bool(token),"READ_TOKEN_MISSING")
    pin=read_pin(args.pin_file)
    envelope=collect_report(Client(token),FixedChargesClient(token),pin,
        matches=matches,clock=lambda:datetime.now(timezone.utc))
    paused(root)
    os.umask(0o077)
    research=root/"data/research"
    need(research.is_dir() and not research.is_symlink(),"RESEARCH_DIRECTORY_REQUIRED")
    folder=Path(tempfile.mkdtemp(prefix="hilega-fee-report-",dir=research))
    private=folder/"fee-report-private.json"
    with private.open("x") as stream:json.dump(envelope,stream,indent=2)
    summary=dict(envelope["assessment"],model=MODEL,
        status="CAPTURED_AGGREGATE_REPORT_RISK_STILL_BLOCKED",
        capture_started_at=envelope["started_at"],capture_completed_at=envelope["completed_at"],
        profile_verified_before_and_after=True,report_locally_signed=True,
        broker_reads_performed=True,database_modified=False,controller_changed=False,
        orders_sent=False,reservation_release_permission=False,
        private_evidence_directory=str(folder))
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    try:main()
    except Exception as exc:
        message=str(exc)
        print(json.dumps(dict(status="STOPPED_FOR_REVIEW",
            reason=message if re.fullmatch("[A-Z][A-Z0-9_]{0,179}",message)
                   else type(exc).__name__,
            production_execution_enabled=False,production_ready=False)))
        raise SystemExit(1)
