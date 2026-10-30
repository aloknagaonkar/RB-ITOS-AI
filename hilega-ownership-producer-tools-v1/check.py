"""Capture a pinned account and review current entry quantity without mutations."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from ownership_review import reconcile_entry
from risk_evidence_audit import read_sources,regular,need,assess


def validate_package(root):
    folder=Path(__file__).resolve().parent
    manifest=json.loads(regular(folder/'manifest.json').read_text())
    for prefix,items in ((folder,manifest['package_sha256']),(root,manifest['installed_source_sha256'])):
        for name,expected in items.items():
            need(hashlib.sha256(regular(prefix/name).read_bytes()).hexdigest()==expected,
                 'PACKAGE_OR_INSTALLED_SOURCE_CHANGED')


def consistent_review(reader,provider,pin,*,clock,mode='LIVE_CLOSED',verifier=None):
    before=reader();assess(before)
    snapshot=provider()
    after=reader()
    need(before==after,'LOCAL_SOURCES_CHANGED_DURING_CAPTURE')
    return reconcile_entry(after,snapshot,pin,as_of=clock(),mode=mode,verifier=verifier)

