"""Pinned private trust/grant file providers and candidate-only issuer implementation."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
from authority_contract import binding,canonical,digest,verify,need


def private_bytes(path,expected,max_size=16384):
    p=Path(path)
    need(p.is_absolute() and not any(q.is_symlink() for q in (p,*p.parents)),'PRIVATE_BINDING_PATH_REQUIRED')
    parent=p.parent.stat();need(parent.st_uid==os.getuid() and stat.S_IMODE(parent.st_mode)&0o077==0,'PRIVATE_BINDING_PARENT_REQUIRED')
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        need(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1
             and stat.S_IMODE(info.st_mode)&0o077==0 and info.st_size<=max_size,'PRIVATE_BINDING_FILE_REQUIRED')
        raw=stream.read(max_size+1)
    need(len(raw)<=max_size and digest(raw)==expected,'PRIVATE_BINDING_HASH_CHANGED')
    return raw


def trust_roots(path,expected,bind):
    bind=binding(bind);value=json.loads(private_bytes(path,expected))
    fields={'model','issuer_id','enabled','account_scope','release_sha256','key_file','key_sha256','production_execution_enabled'}
    need(type(value) is dict and set(value)==fields and value['model']=='HILEGA_PINNED_TRUST_REGISTRY_CANDIDATE_V1'
         and value['enabled'] is True and value['production_execution_enabled'] is False,'EXACT_ENABLED_CANDIDATE_REGISTRY_REQUIRED')
    need(value['account_scope']==bind['account_scope'] and value['release_sha256']==bind['release_sha256'],'TRUST_REGISTRY_SCOPE_OR_RELEASE_CHANGED')
    need(isinstance(value['issuer_id'],str) and 0<len(value['issuer_id'])<=200,'ISSUER_ID_REQUIRED')
    key=private_bytes(value['key_file'],value['key_sha256'],128)
    need(32<=len(key)<=128 and digest(key)!=bind['authority_key_sha256'],'INDEPENDENT_PRIVATE_ISSUER_KEY_REQUIRED')
    return {value['issuer_id']:key}


def grant_file(path,expected):
    return json.loads(private_bytes(path,expected))


def issue_candidate_grant(bind,*,registry_path,registry_sha256,issuer_id,grant_id,issued_at,expires_at):
    """Explicit Python-only signer. The CLI never invokes this on live files."""
    bind=binding(bind);roots=trust_roots(registry_path,registry_sha256,bind)
    need(issuer_id in roots,'APPROVED_REGISTRY_ISSUER_REQUIRED')
    value=dict(model='HILEGA_OFFLINE_AUTHORITY_GRANT_CANDIDATE_V1',issuer_id=issuer_id,grant_id=grant_id,
               binding=bind,issued_at=issued_at,expires_at=expires_at,production_execution_enabled=False)
    value['signature']=hmac.new(roots[issuer_id],canonical(value),hashlib.sha256).hexdigest()
    from authority_contract import aware
    verify(value,bind,roots,aware(issued_at))
    return value
