from pathlib import Path
from datetime import datetime
import shutil
HERE=Path(__file__).resolve().parent; PAYLOAD=HERE/'payload'
def locate_root():
    cwd=Path.cwd()
    for c in (cwd,cwd/'red-bar-lab-standalone-rb-2.0.0-institutional-intelligence'):
        if (c/'red_bar_lab').is_dir(): return c
    raise SystemExit('Run from standalone project root or RB-ITOS-AI repository root.')
root=locate_root()
for source in PAYLOAD.rglob('*'):
    if source.is_file():
        target=root/source.relative_to(PAYLOAD); target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists(): shutil.copy2(target,target.with_name(target.name+'.before_historical_dri_'+datetime.now().strftime('%Y%m%d%H%M%S')))
        shutil.copy2(source,target)
print('Installed additive Historical DRI + opportunity accounting foundation.')
print('No live Red Bar, Committee, Portfolio, queue, or exit rules were modified.')
