from pathlib import Path
import re

INV = Path("frontend/src/historicalReplayInventory.tsx")
OPS = Path("frontend/src/historicalReplayOperations.tsx")

if not INV.exists():
    raise SystemExit("Safe-stop: historicalReplayInventory.tsx not found.")
if not OPS.exists():
    raise SystemExit("Safe-stop: historicalReplayOperations.tsx not found.")

inv = INV.read_text(encoding="utf-8")
ops = OPS.read_text(encoding="utf-8")

# 1) Inventory: do not auto-scan on mount.
patterns = [
    r"\n\s*useEffect\(\(\)=>\{void refresh\(\)\},\[\]\)\s*\n",
    r"\n\s*useEffect\(\(\)\s*=>\s*\{\s*void refresh\(\)\s*\},\s*\[\]\)\s*;?\s*\n",
]
removed_inventory = False
for pattern in patterns:
    new = re.sub(pattern, "\n", inv, count=1)
    if new != inv:
        inv = new
        removed_inventory = True
        break

# Remove useEffect import only when no remaining useEffect exists.
if "useEffect(" not in inv and "useEffect" in inv.split("\n", 1)[0]:
    inv = inv.replace("useEffect,", "", 1).replace(",useEffect", "", 1)

# 2) Replay operations: do not auto-check readiness on date selection.
patterns = [
    r"\n\s*useEffect\(\(\)=>\{\s*if\(sessionDate\)\s*void refreshReadiness\(\)\.catch\(e=>setError\(String\(e\)\)\)\s*\},\[sessionDate\]\)\s*\n",
    r"\n\s*useEffect\(\(\)\s*=>\s*\{\s*if\s*\(sessionDate\)\s*void\s+refreshReadiness\(\)\.catch\([^;]*\)\s*\},\s*\[sessionDate\]\)\s*;?\s*\n",
]
removed_readiness = False
for pattern in patterns:
    new = re.sub(pattern, "\n", ops, count=1)
    if new != ops:
        ops = new
        removed_readiness = True
        break

# 3) Add a bounded request timeout to replay operations if requestJson is still the simple fetch form.
old = """async function requestJson(url:string,init?:RequestInit){
  const r=await fetch(url,init)
  const value=await r.json().catch(()=>({}))
  if(!r.ok) throw new Error(typeof value?.detail==='string'?value.detail:JSON.stringify(value?.detail||value))
  return value
}
"""
new = """async function requestJson(url:string,init?:RequestInit,timeoutMs=20000){
  const controller=new AbortController()
  const timeout=setTimeout(()=>controller.abort(),timeoutMs)
  try{
    const r=await fetch(url,{...init,signal:controller.signal})
    const value=await r.json().catch(()=>({}))
    if(!r.ok) throw new Error(typeof value?.detail==='string'?value.detail:JSON.stringify(value?.detail||value))
    return value
  }catch(e:any){
    if(e?.name==='AbortError') throw new Error(`Request timed out after ${Math.round(timeoutMs/1000)}s: ${url}`)
    throw e
  }finally{
    clearTimeout(timeout)
  }
}
"""
if old in ops:
    ops = ops.replace(old, new, 1)
elif "timeoutMs=20000" not in ops:
    print("WARNING: requestJson shape differs; timeout injection skipped.")

if not removed_inventory:
    print("WARNING: inventory auto-scan effect was not found; inspect manually.")
if not removed_readiness:
    print("WARNING: readiness auto-check effect was not found; inspect manually.")

INV.write_text(inv, encoding="utf-8")
OPS.write_text(ops, encoding="utf-8")

print("Applied Historical Replay UI Request Control V1.")
print("inventory_auto_scan_removed:", removed_inventory)
print("readiness_auto_check_removed:", removed_readiness)
print("request_timeout_present:", "timeoutMs=20000" in ops)
