"""API display cache only. Incremental complete-line reads; no writer locks/writes.

Authoritative audit verification and all strategy readers are untouched.
"""
import json
import os
import threading
import time
from pathlib import Path
from fastapi import HTTPException

class JournalCache:
    def __init__(self,path,start=True):
        self.path=Path(path);self.lock=threading.Lock();self.rows=[];self.offset=0
        self.identity=None;self.ready=False;self.error=None;self.revision=0;self.bytes_read=0
        self.dashboard=None;self.dashboard_revision=-1;self.want_dashboard=False
        if start:threading.Thread(target=self.run,daemon=True,name='hilega-ui-journal').start()

    def refresh(self):
        try:
            handle=self.path.open('rb')
        except FileNotFoundError:
            with self.lock:
                if self.rows or not self.ready:
                    self.revision+=1;self.dashboard=None;self.dashboard_revision=-1
                self.rows=[];self.offset=0;self.identity=None;self.ready=True;self.error=None
            return
        with handle:
            stat=os.fstat(handle.fileno());identity=(stat.st_dev,stat.st_ino)
            with self.lock:
                if identity!=self.identity or stat.st_size<self.offset:
                    self.rows=[];self.offset=0;self.ready=False;self.revision+=1
                    self.dashboard=None;self.dashboard_revision=-1;self.identity=identity
                offset=self.offset
            handle.seek(offset);batch=[];consumed=0
            while consumed<8*1024*1024:
                line=handle.readline()
                if not line or not line.endswith(b'\n'):break
                consumed+=len(line);self.bytes_read+=len(line)
                if line.strip():
                    row=json.loads(line)
                    if not isinstance(row,dict):raise ValueError('INVALID_UI_JOURNAL_ROW')
                    batch.append(row)
                offset=handle.tell()
            with self.lock:
                self.rows.extend(batch);self.offset=offset
                if batch:self.revision+=1
                self.ready=offset>=stat.st_size or (self.ready and bool(self.rows))
                self.error=None

    def refresh_dashboard(self):
        with self.lock:
            if not self.want_dashboard or not self.ready or self.error or self.dashboard_revision==self.revision:return
            rows=list(self.rows);revision=self.revision
        from .hilega_directional_trade_dashboard_v1 import project_directional_shadow_dashboard
        value=project_directional_shadow_dashboard(rows)
        with self.lock:self.dashboard=value;self.dashboard_revision=revision

    def run(self):
        while True:
            try:self.refresh();self.refresh_dashboard()
            except Exception as exc:
                with self.lock:self.error=type(exc).__name__
            time.sleep(.25 if self.ready else .02)

    def read(self):
        with self.lock:
            if not self.ready or self.error:
                raise HTTPException(503,dict(code='UI_AUDIT_CACHE_WARMING_OR_ERROR',error=self.error,read_bytes=self.offset),headers={'Retry-After':'2'})
            return list(self.rows)

    def read_dashboard(self):
        with self.lock:
            self.want_dashboard=True
            if self.dashboard is None or not self.ready or self.error:
                raise HTTPException(503,dict(code='UI_TRADE_CACHE_WARMING_OR_ERROR',error=self.error),headers={'Retry-After':'2'})
            return self.dashboard

_registry={};_lock=threading.Lock()
def entry(path):
    key=str(Path(path).resolve())
    with _lock:
        if key not in _registry:_registry[key]=JournalCache(key)
        return _registry[key]
def read_rows(path):return entry(path).read()
def read_dashboard(path):return entry(path).read_dashboard()
