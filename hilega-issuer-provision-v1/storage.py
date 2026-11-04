"""Create one private issuer key and a disabled registry; never rotate or overwrite."""
import hashlib,hmac,json,os,secrets,stat
from pathlib import Path


def need(ok,label):
    if not ok:raise ValueError(label)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encode(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def private(path):
    p=Path(path);need(p.is_absolute() and not any(q.is_symlink() for q in (p,*p.parents)),'PRIVATE_ISSUER_PATH_REQUIRED')
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        s=os.fstat(f.fileno());parent=p.parent.stat()
        need(stat.S_ISREG(s.st_mode) and s.st_uid==os.getuid() and s.st_nlink==1 and stat.S_IMODE(s.st_mode)&0o077==0
             and parent.st_uid==os.getuid() and stat.S_IMODE(parent.st_mode)&0o077==0 and s.st_size<=131072,'PRIVATE_ISSUER_OWNER_AND_MODE_REQUIRED')
        return f.read(131073)


def syncdir(path):
    fd=os.open(path,os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def create(path,raw,mode):
    p=Path(path);need(not any(q.is_symlink() for q in (p,*p.parents)),'ISSUER_SYMLINK_WRITE_FORBIDDEN')
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as f:
        os.fchmod(f.fileno(),mode);f.write(raw);f.flush();os.fsync(f.fileno())
    syncdir(p.parent)


def private_parent(path,home):
    p=Path(path);home=Path(home)
    need(p.is_absolute() and p.is_relative_to(home) and p!=home and not any(q.is_symlink() for q in (p,*p.parents)),'ISSUER_PARENT_OUTSIDE_APPROVED_HOME')
    current=home
    for part in p.relative_to(home).parts:
        current=current/part
        try:current.mkdir(mode=0o700);syncdir(current.parent)
        except FileExistsError:pass
        s=current.stat();need(current.is_dir() and s.st_uid==os.getuid() and stat.S_IMODE(s.st_mode)==0o700,'EXISTING_ISSUER_PARENT_REQUIRES_REVIEW')


def expected_registry(plan,key_sha):
    return dict(model='HILEGA_PINNED_TRUST_REGISTRY_CANDIDATE_V1',issuer_id=plan['issuer_id'],enabled=False,
        account_scope=plan['account_scope'],release_sha256=plan['release_sha256'],key_file=plan['key_file'],key_sha256=key_sha,production_execution_enabled=False)


def check_layout(plan):
    target=Path(plan['private_parent']);need(Path(plan['key_file'])==target/'issuer.key' and Path(plan['registry_file'])==target/(plan['release_sha256']+'.registry.json'),'EXACT_ISSUER_FILE_LAYOUT_REQUIRED')
    need(plan['production_execution_enabled'] is False and plan['registry_enabled'] is False,'DISABLED_ISSUER_PLAN_REQUIRED')
    return target


def provision(plan,digest,*,recover=False,forbidden=(),random_bytes=secrets.token_bytes,checkpoint=lambda at:None):
    target=check_layout(plan);key_path=Path(plan['key_file']);registry_path=Path(plan['registry_file']);intent_path=target/'PROVISIONING-INTENT.json'
    if not recover:
        need(not target.exists() and not target.is_symlink(),'EXISTING_ISSUER_REQUIRES_EXPLICIT_REVIEW')
        private_parent(target.parent,Path(plan['home']))
        target.mkdir(mode=0o700);syncdir(target.parent)
        key=random_bytes(32)
        need(type(key) is bytes and len(key)==32 and all(not hmac.compare_digest(key,k) for k in forbidden),'INDEPENDENT_RANDOM_ISSUER_KEY_REQUIRED')
        # The durable fingerprint precedes the key file. A partial/missing key
        # can never cause recovery to invent or replace key material.
        intent=dict(model='HILEGA_ISSUER_PROVISIONING_INTENT_V1',plan_sha256=digest,account_scope=plan['account_scope'],
            issuer_id=plan['issuer_id'],release_sha256=plan['release_sha256'],key_file=plan['key_file'],registry_file=plan['registry_file'],key_sha256=sha(key),production_execution_enabled=False)
        create(intent_path,encode(intent),0o600);checkpoint('AFTER_INTENT_BEFORE_KEY')
        create(key_path,key,0o400);del key;checkpoint('AFTER_KEY')
    else:
        intent=json.loads(private(intent_path))
        expected=dict(model='HILEGA_ISSUER_PROVISIONING_INTENT_V1',plan_sha256=digest,account_scope=plan['account_scope'],issuer_id=plan['issuer_id'],
            release_sha256=plan['release_sha256'],key_file=plan['key_file'],registry_file=plan['registry_file'],key_sha256=intent.get('key_sha256'),production_execution_enabled=False)
        need(intent==expected and key_path.is_file(),'EXACT_DURABLE_KEY_RECOVERY_REQUIRED')
    key=private(key_path);need(len(key)==32 and sha(key)==intent['key_sha256'],'ISSUER_KEY_CHANGED_OR_INCOMPLETE')
    need(all(not hmac.compare_digest(key,k) for k in forbidden),'ISSUER_KEY_NOT_INDEPENDENT');del key
    expected=encode(expected_registry(plan,intent['key_sha256']))
    if registry_path.exists():need(private(registry_path)==expected,'EXTERNAL_REGISTRY_CHANGE_REQUIRES_REVIEW')
    else:create(registry_path,expected,0o400)
    checkpoint('AFTER_REGISTRY')
    receipt=dict(status='REAL_ISSUER_MATERIAL_PREPARED_REGISTRY_DISABLED',plan_sha256=digest,issuer_id=plan['issuer_id'],
        account_scope=plan['account_scope'],release_sha256=plan['release_sha256'],key_file=plan['key_file'],key_sha256=intent['key_sha256'],
        registry_file=plan['registry_file'],registry_sha256=sha(expected),real_issuer_key_material_prepared=True,registry_enabled=False,production_execution_enabled=False,
        registration_activated=False,live_database_enrolled=False,controller_resumed=False)
    receipt_path=target/'PROVISIONING-RECEIPT.json'
    if receipt_path.exists():need(private(receipt_path)==encode(receipt),'ISSUER_RECEIPT_CHANGED')
    else:create(receipt_path,encode(receipt),0o600)
    return receipt


def status(plan,digest):
    target=check_layout(plan);intent=json.loads(private(target/'PROVISIONING-INTENT.json'))
    need(intent['plan_sha256']==digest,'ISSUER_STATUS_PLAN_CHANGED')
    key=private(Path(plan['key_file']));need(len(key)==32 and sha(key)==intent['key_sha256'],'ISSUER_STATUS_KEY_CHANGED');del key
    expected=encode(expected_registry(plan,intent['key_sha256']));need(private(Path(plan['registry_file']))==expected,'ISSUER_STATUS_REGISTRY_CHANGED')
    receipt=json.loads(private(target/'PROVISIONING-RECEIPT.json'))
    need(receipt['plan_sha256']==digest and receipt['key_sha256']==intent['key_sha256'] and receipt['registry_sha256']==sha(expected)
         and receipt['registry_enabled'] is False and receipt['production_execution_enabled'] is False,'ISSUER_STATUS_RECEIPT_CHANGED')
    return receipt
