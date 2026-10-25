"""Existing installed-controller/adapter/ownership fixture composed without tests."""
import hashlib,importlib.util,json
from pathlib import Path
from consumer import ReleaseConsumer
ROOT=Path(__file__).resolve().parent.parent
AT='2026-10-26T09:25:00+05:30';END='2026-10-26T09:25:05+05:30'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def modules():
    for rel,expected in json.loads(Path(__file__).with_name('dependencies.json').read_text()).items():
        p=ROOT/rel
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError('DEPENDENCY_CHANGED_'+rel)
    folder=ROOT/'hilega-production-ownership-evidence-link'
    support=load('release_ownership_support',folder/'support.py');evidence=load('release_ownership_evidence',folder/'evidence.py')
    return support,evidence,support.dependencies()

def build_partial(path):
    helper,evidence,fixtures=modules();s,b,clock,link,entry,contract=fixtures.build(path)
    link.dispatch_prepared(entry['id'],contract,as_of=AT)
    proof=evidence.EvidenceLink(link,Path(path)/'evidence.sqlite');proof.register_entry(entry['id'])
    oid=link.adapter.status()['requests'][0]['order_id'];link.adapter.transport.fill(oid,20);link.adapter.cancel(entry['id'])
    trades=[helper.fill(oid,'BUY',20,at=AT,trade_id='t1')]
    data=helper.snapshot(link.adapter,sid='partial',at=AT,trades=trades);proof.reconcile(data,as_of=AT)
    return dict(service=s,broker=b,link=link,entry=entry,evidence=proof,helper=helper,trades=trades,snapshot=data,consumer=ReleaseConsumer(proof))

def add_exit(env,*,filled=True):
    h=env['helper'];link=env['link'];p=env['evidence'];h.prepare_fixture_exit(link,'exit1',20,at=END)
    p.register_exit('exit1',env['entry']['id'],as_of=END);link.adapter.submit('exit1')
    oid=next(r['order_id'] for r in link.adapter.status()['requests'] if r['request_id']=='exit1')
    if filled:
        link.adapter.transport.fill(oid,20);env['trades'].append(h.fill(oid,'SELL',20,at=END,trade_id='t2'))
    env['snapshot']=h.snapshot(link.adapter,sid='flat' if filled else 'pending-exit',at=END,trades=env['trades'])
    env['evidence'].reconcile(env['snapshot'],as_of=END);return env

def build_flat(path):return add_exit(build_partial(path))
def consume(env,request_id='release1',as_of=END):return env['consumer'].consume(env['entry']['id'],snapshot_id=env['snapshot']['snapshot_id'],request_id=request_id,as_of=as_of)
