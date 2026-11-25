"""Recover to research-only cache and optionally export exact validated source bytes."""
from pathlib import Path
import shutil

def resolve_sessions(w,index,target,*,source,cache_root,export_inputs):
    recovered=[];cache_root=Path(cache_root)
    for day in [*w.required_sessions(target),target]:
        key=str(day)
        try:
            if key not in index:raise ValueError('CACHE_MISSING')
            w.read_session(index[key],day)
        except (ValueError,KeyError,TypeError,OSError):
            if source is None:raise ValueError('REQUIRED_CANDLE_SESSION_MISSING_OR_INVALID:'+key) from None
            index[key]=w.save_session(cache_root,day,w.fetch_session(source,day))
            recovered.append(key);print('RECOVERED_READ_ONLY:',key,flush=True)
        if export_inputs:
            dest=cache_root/(key+'.json');original=Path(index[key])
            if dest.resolve()!=original.resolve():
                cache_root.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,dest)
            # Fingerprint/read the exact exported bytes throughout both strategy replays.
            index[key]=dest
    return recovered
