"""Lock installed runtime distributions to matching downloaded wheels; never installs."""
import hashlib
import importlib.metadata as metadata
from pathlib import Path,PurePosixPath
from email.parser import BytesParser
import subprocess
import sys
from zipfile import ZipFile
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.utils import canonicalize_name


def need(ok,reason):
    if not ok:raise ValueError(reason)


def payload(name):
    return not any(p.endswith('.dist-info') for p in PurePosixPath(name).parts) and name.endswith(('.py','.so','.pyd','.pyi','py.typed'))


def check_wheel(wheel,dist):
    with ZipFile(wheel) as z:
        names=z.namelist();need(len(names)==len(set(names)) and len(names)<2000,'INVALID_WHEEL_MEMBERS')
        need(all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts for n in names),'WHEEL_PATH_INVALID')
        need(sum(i.file_size for i in z.infolist())<100_000_000,'WHEEL_EXPANSION_TOO_LARGE')
        metas=[n for n in names if n.endswith('.dist-info/METADATA')];need(len(metas)==1,'UNIQUE_WHEEL_METADATA_REQUIRED')
        m=BytesParser().parsebytes(z.read(metas[0]));name=canonicalize_name(dist.metadata['Name'])
        need(canonicalize_name(m['Name'])==name and m['Version']==dist.version,'EXACT_INSTALLED_WHEEL_REQUIRED')
        need(sorted(m.get_all('Requires-Dist',[]))==sorted(dist.requires or []),'WHEEL_REQUIREMENTS_METADATA_DIFFERS')
        wheel_files={n:hashlib.sha256(z.read(n)).hexdigest() for n in names if payload(n)}
    installed={}
    for item in dist.files or []:
        n=str(item)
        if not payload(n):continue
        path=Path(dist.locate_file(item)).absolute()
        need(not any(p.is_symlink() for p in [path,*path.parents]),'REGULAR_INSTALLED_PAYLOAD_REQUIRED')
        installed[n]=hashlib.sha256(path.read_bytes()).hexdigest()
    need(wheel_files and installed==wheel_files,'INSTALLED_RUNTIME_PAYLOAD_DIFFERS_FROM_WHEEL: '+name)
    digest=hashlib.sha256(Path(wheel).read_bytes()).hexdigest()
    return dict(distribution=name,version=dist.version,wheel_filename=Path(wheel).name,wheel_sha256=digest,
        payload_hashes=wheel_files,installed_python_and_native_payload_match=True,
        requirement=name+'=='+dist.version+' --hash=sha256:'+digest)


def lock_runtime(output,roots=('python-dotenv','pydantic')):
    output.mkdir(mode=0o700);queue=list(roots);seen=set();rows=[]
    while queue:
        name=canonicalize_name(queue.pop())
        if name in seen:continue
        seen.add(name);dist=metadata.distribution(name)
        for text in dist.requires or []:
            req=Requirement(text)
            if req.marker is not None and not req.marker.evaluate({'extra':''}):continue
            dependency=metadata.distribution(req.name)
            need(not req.url and dependency.version in req.specifier,'UNREVIEWED_OR_UNSATISFIED_DISTRIBUTION_REQUIREMENT')
            queue.append(req.name)
        print('Verifying wheel:',name,dist.version,flush=True)
        destination=output/name;destination.mkdir()
        try:
            r=subprocess.run([sys.executable,'-m','pip','--isolated','--disable-pip-version-check','download',
                '--index-url','https://pypi.org/simple','--no-deps','--only-binary=:all:',
                '--dest',str(destination),name+'=='+dist.version],capture_output=True,timeout=60)
        except subprocess.TimeoutExpired:raise ValueError('WHEEL_DOWNLOAD_TIMEOUT: '+name) from None
        need(r.returncode==0,'WHEEL_DOWNLOAD_FAILED_WITHOUT_INSTALL: '+name)
        found=list(destination.glob('*.whl'));need(len(found)==1,'UNIQUE_WHEEL_REQUIRED')
        rows.append(check_wheel(found[0],dist))
    rows.sort(key=lambda r:r['distribution'])
    (output/'requirements-runtime.lock').write_text('--only-binary=:all:\n'+'\n'.join(r['requirement'] for r in rows)+'\n')
    return dict(distributions=rows,optional_extras_enabled=False,packages_installed=False,
        wheel_lock_scope='CURRENT_INTERPRETER_PLATFORM_WORKER_RUNTIME')
