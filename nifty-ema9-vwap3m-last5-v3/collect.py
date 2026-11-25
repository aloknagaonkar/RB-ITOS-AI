"""Read-only GET requests for pinned five-session research; never sends orders."""
import json,os,re,time,gzip
import httpx
from datetime import datetime,date,timedelta,time as clock
from urllib.parse import quote,urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from pathlib import Path
import strategy
DAYS=['2026-10-29','2026-10-30','2026-11-02','2026-11-03','2026-11-04']
API='https://api.upstox.com'
INDEX='NSE_INDEX|Nifty 50'
class DataError(RuntimeError):pass
LAST_REQUEST={}
AUTH_DIAGNOSTICS={}
PUBLIC_INSTRUMENTS='https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz'

def endpoint_label(path):
    if path=='/v2/instruments/search':return 'INSTRUMENT_SEARCH'
    if '/intraday/' in path:return 'INTRADAY_CANDLES_V3'
    return 'HISTORICAL_CANDLES_V3'

def safe_http_failure(status,path,body=b''):
    codes=[]
    try:
        data=json.loads(body)
        for item in data.get('errors',[]):
            code=str(item.get('errorCode',''))
            if re.fullmatch(r'UDAPI[0-9]{3,8}',code):codes.append(code)
    except (ValueError,TypeError,AttributeError):pass
    LAST_REQUEST.update(endpoint=endpoint_label(path),http_status=status,provider_error_codes=codes)
    return 'PROVIDER_HTTP_'+str(status)+' endpoint='+endpoint_label(path)+' codes='+(','.join(codes) or 'NOT_RETURNED')


def get_json(path,token,params=None):
    if not (path=='/v2/instruments/search' or path.startswith('/v3/historical-candle/')):raise DataError('GET_PATH_NOT_ALLOWED')
    url=API+path+('?' + urlencode(params) if params else '')
    LAST_REQUEST.clear();LAST_REQUEST.update(endpoint=endpoint_label(path),http_status=None,provider_error_codes=[])
    print('GET',endpoint_label(path),flush=True)
    headers={'Authorization':'Bearer '+token,'Accept':'application/json'}
    for attempt in range(3):
        try:
            response=httpx.get(url,headers=headers,timeout=30,follow_redirects=False)
        except httpx.RequestError:
            raise DataError('PROVIDER_NETWORK_ERROR endpoint='+endpoint_label(path)) from None
        LAST_REQUEST['http_status']=response.status_code
        if response.status_code!=200:
            if response.status_code in [429,500,502,503,504] and attempt<2:
                time.sleep(1+attempt);continue
            raise DataError(safe_http_failure(response.status_code,path,response.content[:65536]))
        try:body=response.json()
        except ValueError:raise DataError('PROVIDER_INVALID_JSON endpoint='+endpoint_label(path)) from None
        if not isinstance(body,dict) or body.get('status')!='success':raise DataError('PROVIDER_NON_SUCCESS_STATUS endpoint='+endpoint_label(path))
        time.sleep(.4)
        return body
    raise DataError('PROVIDER_RETRY_EXHAUSTED')

def token_from_env():
    try:
        from dotenv import load_dotenv,dotenv_values
    except ImportError:raise DataError('PYTHON_DOTENV_REQUIRED_FROM_PROJECT_VENV') from None
    env_token=os.getenv('UPSTOX_ACCESS_TOKEN','').strip()
    file_token=(dotenv_values(Path.cwd()/'.env').get('UPSTOX_ACCESS_TOKEN') or '').strip()
    AUTH_DIAGNOSTICS.update(token_source='PROCESS_ENV' if env_token else 'REPO_DOTENV' if file_token else 'MISSING',process_env_present=bool(env_token),dotenv_present=bool(file_token),process_and_dotenv_match=(env_token==file_token) if env_token and file_token else None)
    load_dotenv(Path.cwd()/'.env',override=False)
    token=os.getenv('UPSTOX_ACCESS_TOKEN','').strip()
    if not token:raise DataError('UPSTOX_ACCESS_TOKEN_MISSING_USE_EXISTING_VM_AUTH_SETUP')
    return token

def choose_contract(rows):
    candidates={}
    for r in rows:
        if r.get('instrument_type')!='FUT' or r.get('segment')!='NSE_FO' or r.get('underlying_symbol')!='NIFTY' or r.get('underlying_key')!=INDEX:continue
        try:
            value=r['expiry']
            expiry=datetime.fromtimestamp(float(value)/1000,strategy.IST).date() if isinstance(value,(int,float)) or str(value).isdigit() else date.fromisoformat(value)
        except (ValueError,KeyError,TypeError):continue
        if expiry<date.fromisoformat(DAYS[-1]):continue
        if not r.get('instrument_key') or not r.get('trading_symbol'):continue
        candidates[r['instrument_key']]=dict(r,expiry=expiry.isoformat())
    if not candidates:raise DataError('NO_NIFTY_FUTURES_CONTRACT')
    r=min(candidates.values(),key=lambda r:(r['expiry'],r['instrument_key']))
    # These fixed dates are after Oct27 expiry and before November expiry.
    # Current instrument search cannot recover an expired November contract later.
    if r['expiry'][:7]!='2026-11':raise DataError('NOVEMBER_2026_FRONT_CONTRACT_UNAVAILABLE_DO_NOT_SUBSTITUTE_ANOTHER_MONTH')
    return dict(instrument_type='FUT',instrument_key=r['instrument_key'],trading_symbol=r['trading_symbol'],expiry=r['expiry'],source='UPSTOX_INSTRUMENT_SEARCH_NOVEMBER_FRONT',underlying_key=INDEX)

def resolve_search(token):
    rows=[]
    for expiry in ['current_month','next_month']:
        for page in range(1,4):
            body=get_json('/v2/instruments/search',token,dict(query='NIFTY',exchanges='NSE',segments='FO',instrument_types='FUT',expiry=expiry,page_number=page,records=30))
            data=body.get('data')
            if not isinstance(data,list):raise DataError('SEARCH_DATA_NOT_LIST')
            rows.extend(data)
            if len(data)<30:break
    return choose_contract(rows)

def resolve(token,instrument_file=None):
    """Official public catalogue first; no Authorization header is sent to assets."""
    if instrument_file is not None:
        raw=Path(instrument_file).read_bytes();source='LOCAL_PUBLIC_INSTRUMENT_CATALOGUE'
    else:
        print('GET PUBLIC_NSE_INSTRUMENT_CATALOGUE (no authentication)',flush=True)
        try:
            request=Request(PUBLIC_INSTRUMENTS,headers={'Accept':'application/json','User-Agent':'NiftyResearch/2'},method='GET')
            with urlopen(request,timeout=45) as response:raw=response.read(40000001)
            if len(raw)>40000000:raise DataError('PUBLIC_CATALOGUE_SIZE_LIMIT')
            source='UPSTOX_PUBLIC_NSE_CATALOGUE'
        except HTTPError as e:
            LAST_REQUEST.update(endpoint='PUBLIC_INSTRUMENT_CATALOGUE',http_status=e.code,provider_error_codes=[])
            print('Public catalogue unavailable HTTP',e.code,'; trying instrument search...',flush=True)
            return resolve_search(token)
        except URLError:
            print('Public catalogue network unavailable; trying instrument search...',flush=True)
            return resolve_search(token)
    try:
        if raw[:2]==b'\x1f\x8b':raw=gzip.decompress(raw)
        rows=json.loads(raw)
    except (ValueError,OSError):raise DataError('PUBLIC_CATALOGUE_INVALID_GZIP_OR_JSON') from None
    if not isinstance(rows,list):raise DataError('PUBLIC_CATALOGUE_NOT_LIST')
    contract=choose_contract(rows);contract['source']=source
    return contract

def normalize(body,day):
    rows=body.get('data',{}).get('candles')
    if not isinstance(rows,list):raise DataError('CANDLES_NOT_LIST')
    regular={};outside=[]
    for row in rows:
        if not isinstance(row,list) or len(row)<6:raise DataError('INVALID_CANDLE_SCHEMA')
        try:
            at=datetime.fromisoformat(str(row[0]).replace('Z','+00:00'))
            if at.tzinfo is None:raise DataError('NAIVE_PROVIDER_TIME')
            at=at.astimezone(strategy.IST)
            if at.date().isoformat()!=day:raise DataError('WRONG_PROVIDER_DATE')
            d=dict(timestamp=at.isoformat(),open=float(row[1]),high=float(row[2]),low=float(row[3]),close=float(row[4]),volume=float(row[5]))
            if len(row)>6 and row[6] is not None:d['open_interest']=float(row[6])
        except (ValueError,TypeError):raise DataError('INVALID_CANDLE_VALUE') from None
        if clock(9,15)<=at.time()<clock(15,30):
            if at.isoformat() in regular:raise DataError('DUPLICATE_PROVIDER_MINUTE')
            regular[at.isoformat()]=d
        else:outside.append(at.isoformat())
    return [regular[k] for k in sorted(regular)],outside

def fetch_day(token,key,day,contract=None):
    now=datetime.now(strategy.IST)
    if date.fromisoformat(day)>now.date() or (day==now.date().isoformat() and now.time()<clock(15,35)):raise DataError('SESSION_NOT_YET_COMPLETE')
    encoded=quote(key,safe='')
    path=f'/v3/historical-candle/intraday/{encoded}/minutes/1' if day==now.date().isoformat() else f'/v3/historical-candle/{encoded}/minutes/1/{day}/{day}'
    body=get_json(path,token);rows,outside=normalize(body,day)
    data=dict(session_date=day,captured_at=now.isoformat(),candles=rows,provenance=dict(endpoint_type='INTRADAY_V3' if '/intraday/' in path else 'HISTORICAL_V3',instrument_key=key,study_window='09:15 inclusive to 15:30 exclusive',excluded_outside_study_window=outside,provider_candle_count=len(body.get('data',{}).get('candles',[]))))
    if contract:data['contract']=contract
    else:data['underlying']=INDEX
    strategy.validate(data,require_futures=contract is not None)
    return data

def collect(output,instrument_file=None):
    token=token_from_env()
    (output/'auth-diagnostics.json').write_text(json.dumps(AUTH_DIAGNOSTICS,indent=2))
    contract=resolve(token,instrument_file=instrument_file);input_root=output/'inputs';input_root.mkdir()
    (output/'contract.json').write_text(json.dumps(contract,indent=2));result={}
    for day in DAYS:
        print('Fetching',day,contract['trading_symbol'],'and NIFTY index...',flush=True)
        future=fetch_day(token,contract['instrument_key'],day,contract);index=fetch_day(token,INDEX,day)
        for name,data in [('futures',future),('index',index)]:
            path=input_root/(name+'-'+day+'.json');path.write_text(json.dumps(data,indent=2))
        result[day]=(future,index)
    return contract,result
