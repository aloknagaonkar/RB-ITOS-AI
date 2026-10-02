from pathlib import Path
CSS=Path("frontend/src/historicalOiResearch.css")
text=CSS.read_text(encoding="utf-8") if CSS.exists() else ""
rule='''.hoi-horizon-line{display:grid!important;grid-template-columns:38px 1fr!important;gap:8px!important;align-items:start!important}
.hoi-horizon-line b{white-space:normal;text-align:left!important;font-size:.78rem}
'''
if ".hoi-horizon-line" not in text:
    CSS.write_text(text.rstrip()+"\n"+rule+"\n",encoding="utf-8")
print("Patched Historical OI audit CSS.")
