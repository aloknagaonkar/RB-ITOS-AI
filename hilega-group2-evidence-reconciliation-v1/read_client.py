"""Only two documented order-specific GET endpoints; redirects, retries and mutations unavailable."""
import json,re
from urllib.request import Request
from urllib.parse import urlencode
from urllib.error import HTTPError

EXTRA={'history':'/v2/order/history','order_trades':'/v2/order/trades'}
def get(client,kind,order_id):
    if kind not in EXTRA:raise ValueError('AUDIT_ENDPOINT_NOT_ALLOWED')
    if not isinstance(order_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',order_id):raise ValueError('SAFE_ORDER_IDENTIFIER_REQUIRED')
    path=EXTRA[kind]+'?'+urlencode({'order_id':order_id})
    req=Request('https://api.upstox.com'+path,headers={'Authorization':'Bearer '+client.token,'Accept':'application/json','User-Agent':'RB-ITOS-AI/1.0 (read-only readiness validation)'},method='GET')
    try:
        with client.opener.open(req,timeout=8) as response:
            raw=response.read(8_000_001);date=response.headers.get('Date')
        if len(raw)>8_000_000:raise ValueError('AUDIT_RESPONSE_TOO_LARGE')
        value=json.loads(raw)
        if not isinstance(value,dict) or value.get('status')!='success' or not isinstance(value.get('data'),list):raise ValueError('AUDIT_ENDPOINT_RESPONSE_INVALID')
        return value,date
    except HTTPError as exc:raise ValueError('AUDIT_HTTP_'+str(exc.code)) from None
    except (OSError,TimeoutError):raise ValueError('AUDIT_NETWORK_OR_TIMEOUT') from None
