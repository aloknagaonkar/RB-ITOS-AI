"""Read-only band-independent WMA(RSI) and price EMA10 sideways research."""
import argparse,csv,importlib.util,sys,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path

BASE_FILE=Path(__file__).resolve().parent.parent/'hilega_wma21_sideways_research/analyze.py'
def load_base():
    if not BASE_FILE.is_file():raise FileNotFoundError('Install hilega_wma21_sideways_research first')
    spec=importlib.util.spec_from_file_location('sideways_base',BASE_FILE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def policies():
    return [dict(id=f'N{n}_R{r}_NET{d}_C{c}_EMA{mode}',n=n,max_range=r,max_net=d,min_crossings=c,ema_mode=mode,ema_mean_limit=1,ema_range_limit=3) for n in (3,5) for r in (.5,1,2) for d in (.25,.5,1) for c in (0,1) for mode in ('NONE','FLAT','MIXED','FLAT_AND_MIXED')]

def is_sideways(p,f):
    if not f:return False
    # Deliberately independent of WMA's absolute level.
    wma_flat=f['wma_range']<=p['max_range'] and abs(f['wma_net_change'])<=p['max_net'] and f['rsi_wma_crossings']>=p['min_crossings']
    if not wma_flat:return False
    if p['ema_mode']=='NONE':return True
    keys=('ema_mean3','ema_range3','ema_sign_changes6')
    if any(f.get(k) is None for k in keys):return False
    flat=abs(f['ema_mean3'])<=p['ema_mean_limit'] and f['ema_range3']<=p['ema_range_limit']
    mixed=f['ema_sign_changes6']>=2
    return flat if p['ema_mode']=='FLAT' else mixed if p['ema_mode']=='MIXED' else flat and mixed

def feature_wrapper(base_features,price_lookup):
    def feature(rows,n):
        f=base_features(rows,n)
        if not f:return None
        at=f['available_at'];price=price_lookup.get(at)
        if not price:raise ValueError('MATCHING_PRICE_EMA_EVIDENCE_MISSING:'+at)
        stamps=[(datetime.fromisoformat(at)-timedelta(minutes=i*5)).isoformat() for i in (2,1,0)]
        # The WMA window resets daily, so these three EMA observations must also be within it.
        rr=[price_lookup.get(t) for t in stamps]
        if not all(rr):raise ValueError('ADJACENT_PRICE_EMA_EVIDENCE_MISSING:'+at)
        vals=[float(r['ema10']) for r in rr]
        f.update(ema10=float(price['ema10']),ema_slope=float(price['slope']),ema_mean3=float(price['mean3']),ema_sign_changes6=int(price['sign_changes6']),ema_range3=max(vals)-min(vals),price_close=float(price['close']))
        return f
    return feature

def analyze(a):
    m=load_base();path=a.input_root/'candles.csv'
    with path.open(newline='') as f:prices=list(csv.DictReader(f))
    lookup={r['available_at']:r for r in prices}
    if len(lookup)!=len(prices):raise ValueError('DUPLICATE_PRICE_EMA_TIMESTAMPS')
    m.features=feature_wrapper(m.features,lookup);m.candidates=policies;m.sideways=is_sideways
    print('WMA flatness has NO 45-55 band requirement. WMA values use RSI units; EMA range/slope use Nifty points.',flush=True)
    print('EMA FLAT: |mean3 slope| <=1 AND range of latest three EMA values <=3. MIXED: >=2 sign changes among latest six slopes.',flush=True)
    print('Missing feature history remains unavailable, not classified sideways. Fixed baseline entries/exits; no live changes.',flush=True)
    print('The inspection column Band all 45-55 is context only; it is NOT a gate in this study.',flush=True)
    m.analyze(a)
    report_path=a.output_root/'report.json';report=json.loads(report_path.read_text())
    report['method']='Band-independent WMA range/net/crossing entry selection, optionally combined with causal price EMA flatness/mixed slopes. Original entry and exit lifecycle held fixed.'
    report['ema_flat_definition']='abs(mean of latest 3 slopes)<=1 Nifty point AND latest 3 EMA values range<=3 Nifty points'
    report['ema_mixed_definition']='At least two sign changes among latest six EMA slopes'
    report['study_source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['base_formatter_sha256']=hashlib.sha256(BASE_FILE.read_bytes()).hexdigest()
    report_path.write_text(json.dumps(report,indent=2))

def self_test():
    m=load_base();m.self_test()
    p=dict(n=3,max_range=1,max_net=.5,min_crossings=1,ema_mode='FLAT_AND_MIXED',ema_mean_limit=1,ema_range_limit=3)
    f=dict(wma21=43.5,wma_range=.4,wma_net_change=.2,rsi_wma_crossings=2,ema_mean3=.1,ema_range3=1.5,ema_sign_changes6=3)
    assert is_sideways(p,f) # Flat at WMA43.5 is now permitted.
    assert not is_sideways(p,dict(f,ema_range3=8)) # Net cancellation alone insufficient.
    assert not is_sideways(p,dict(f,ema_sign_changes6=0))
    assert is_sideways(dict(p,ema_mode='NONE'),dict(f,ema_mean3=5))
    assert not is_sideways(p,dict(f,wma_range=4))
    lookup={}
    for t,ema in [('13:00',22000),('13:05',22001),('13:10',22000.5),('13:15',25000)]:lookup['2026-10-12T'+t+':00+05:30']=dict(ema10=ema,slope=.1,mean3=.1,sign_changes6=2,close=22000)
    wrapper=feature_wrapper(lambda rows,n:dict(available_at='2026-10-12T13:10:00+05:30'),lookup)
    assert wrapper([],3)['ema_range3']==1 # Future13:15 value cannot leak.
    print('PASS: band-independent flatness, joint gates, oscillation guard and causal EMA join')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input-root',type=Path,default=Path('data/historical-evidence/hilega-ema10-trend-research-v1'));p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-combined-sideways-research-v1'));p.add_argument('--inspect-date',default='2026-10-12');p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test:self_test()
    else:analyze(a)
