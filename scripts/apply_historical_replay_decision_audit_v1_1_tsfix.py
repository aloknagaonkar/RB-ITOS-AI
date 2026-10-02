from pathlib import Path

UI = Path("frontend/src/historicalReplay.tsx")
if not UI.exists():
    raise SystemExit("Safe-stop: frontend/src/historicalReplay.tsx not found.")

text = UI.read_text(encoding="utf-8")

old1 = """    if(c2Confirmed){c2Result='PASS';c2Actual=c2Confirmed.detail||c2Confirmed.status;c2Reason=c2Confirmed.reason}
"""
new1 = """    if(c2Confirmed){
      c2Result='PASS'
      c2Actual=c2Confirmed.detail||c2Confirmed.status||'C2 confirmed'
      c2Reason=c2Confirmed.reason||'The same ALL3 direction remained confirmed at C2.'
    }
"""

old2 = """    else if(c2Decision){c2Result=c2Decision.status==='CLASSIFIED'?'PASS':gateResultFromStatus(c2Decision.display_result||c2Decision.status);c2Actual=c2Decision.detail||c2Decision.status;c2Reason=c2Decision.reason}
"""
new2 = """    else if(c2Decision){
      c2Result=c2Decision.status==='CLASSIFIED'?'PASS':gateResultFromStatus(c2Decision.display_result||c2Decision.status)
      c2Actual=c2Decision.detail||c2Decision.status||'C2 decision recorded'
      c2Reason=c2Decision.reason||'The recorded C2 decision determined whether the candidate could continue.'
    }
"""

if old1 not in text:
    raise SystemExit("Safe-stop: c2Confirmed line not found in expected form.")
if old2 not in text:
    raise SystemExit("Safe-stop: c2Decision line not found in expected form.")

text = text.replace(old1, new1, 1)
text = text.replace(old2, new2, 1)

UI.write_text(text, encoding="utf-8")
print("Applied Decision Audit V1.1 TypeScript strict-null fix.")
