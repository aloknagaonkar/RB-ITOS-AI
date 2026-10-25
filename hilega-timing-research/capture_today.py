"""Read-only full-session market data + audit export. No orders or service changes."""
import argparse
from datetime import datetime,timedelta
import json
import os
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile, ZIP_DEFLATED
from zoneinfo import ZoneInfo
import httpx
from dotenv import dotenv_values

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base-zip',type=Path,required=True)
    ap.add_argument('--date',default='2026-10-21')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    now=datetime.now(ZoneInfo('Asia/Kolkata'))
    if now.date().isoformat()!=args.date:raise ValueError('INTRADAY_ENDPOINT_REQUIRES_TODAY')
    if now.strftime('%H:%M')<'14:56':raise ValueError('WAIT_UNTIL_1456_IST_FOR_COMPLETE_CUTOFF_MINUTE')
    token=os.getenv('UPSTOX_ACCESS_TOKEN') or dotenv_values('.env').get('UPSTOX_ACCESS_TOKEN')
    if not token:raise ValueError('ACCESS_TOKEN_MISSING')
    url='https://api.upstox.com/v3/historical-candle/intraday/'+quote('NSE_INDEX|Nifty 50',safe='')+'/minutes/1'
    response=httpx.get(url,headers={'Authorization':'Bearer '+token,'Accept':'application/json'},timeout=30)
    if response.status_code!=200:raise ValueError('MARKET_DATA_HTTP_'+str(response.status_code))
    body=response.json()
    if body.get('status')!='success':raise ValueError('MARKET_DATA_UNSUCCESSFUL')
    candles=[]
    for r in body.get('data',{}).get('candles',[]):
        at=datetime.fromisoformat(r[0]).astimezone(now.tzinfo)
        if at.date()==now.date() and at+timedelta(minutes=1)<=now:
            candles.append(dict(timestamp=at.isoformat(),open=r[1],high=r[2],low=r[3],close=r[4],volume=r[5] if len(r)>5 else 0))
    candles.sort(key=lambda r:r['timestamp'])
    if not any(r['timestamp'][11:16]=='14:55' for r in candles):raise ValueError('CUTOFF_MINUTE_NOT_AVAILABLE_YET')
    rows=[]
    audit=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl')
    with audit.open() as f:
        for line in f:
            if not line.endswith('\n') or args.date not in line:continue
            rows.append(json.loads(line))
    if not rows:raise ValueError('TODAY_AUDIT_MISSING')
    args.output.mkdir(parents=True,exist_ok=True)
    candle_path=args.output/'session-input.json'
    zip_path=args.output/'timing-input.zip'
    if zip_path.resolve()==args.base_zip.resolve():raise ValueError('EXPORT_MUST_NOT_OVERWRITE_INPUT_ZIP')
    if zip_path.exists() or candle_path.exists():raise ValueError('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    candle_path.write_text(json.dumps(dict(session_date=args.date,underlying='NSE_INDEX|Nifty 50',
        captured_at=now.isoformat(),input_basis='LATER_API_CANDLES',candles=candles),indent=2))
    with ZipFile(args.base_zip) as source,ZipFile(zip_path,'w',ZIP_DEFLATED) as target:
        for name in source.namelist():
            if name.startswith('candles/') and name.endswith('.json'):
                target.writestr(name,source.read(name))
        target.writestr('today-audit.json',json.dumps(rows))
    print(json.dumps(dict(status='CAPTURED',candles=len(candles),audit_records=len(rows),
        session_input=str(candle_path),input_zip=str(zip_path),orders_sent=False)))

if __name__=='__main__':main()
