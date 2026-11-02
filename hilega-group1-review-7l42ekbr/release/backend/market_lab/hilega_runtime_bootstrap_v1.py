"""Explicit closed bootstrap; no environment activation or implicit Store creation."""
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing


def need(ok,reason):
    if not ok:raise ValueError(reason)


def existing_adapter(path,scope):
    p=Path(path)
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in [p,*p.parents]),'EXISTING_REGULAR_ADAPTER_REQUIRED')
    with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        row=db.execute('SELECT data FROM meta WHERE id=1').fetchone()
        need(row is not None and json.loads(row[0])==dict(scope=scope,mode='LIVE_CLOSED'),'BOOTSTRAP_ADAPTER_META_CHANGED')
        names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        need({'meta','requests','attempts','receipts'}<=names,'EXISTING_ADAPTER_SCHEMA_REQUIRED')
        db.rollback()


class RegisteredBootstrap:
    """Source/store are explicitly supplied by reviewed Python assembly, never discovered."""
    def __init__(self,source,store,journal,config_path,config_sha256,*,clock):
        self.source,self.store,self.journal=source,store,journal
        self.path,self.digest,self.clock=config_path,config_sha256,clock
        self.factory=None

    def poll(self):
        from market_lab.hilega_execution_port_v1 import adapter as port
        from market_lab.hilega_execution_session_factory_v1 import closed,ExecutionSessionFactory
        try:port.require_live_clearance()
        except port.GateClosed:return closed()
        need(type(self.digest) is str and len(self.digest)==64 and all(c in '0123456789abcdef' for c in self.digest),'PUBLIC_CONTEXT_DIGEST_REQUIRED')
        need(type(self.store) is port.Store and self.store.mode=='LIVE_CLOSED','EXPLICIT_EXISTING_STORE_REQUIRED')
        existing_adapter(self.store.path,self.store.scope)
        if self.factory is None:
            from market_lab.hilega_private_context_v1 import PrivateContextLoader
            self.factory=ExecutionSessionFactory(PrivateContextLoader(self.source,self.store,self.journal,
                self.path,self.digest,clock=self.clock))
        return self.factory.poll(self.source,self.journal)
