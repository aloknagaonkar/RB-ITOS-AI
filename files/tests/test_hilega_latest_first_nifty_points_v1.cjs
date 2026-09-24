const fs=require('fs')
const path='frontend/src/hilegaDecisionTable.tsx'
const s=fs.readFileSync(path,'utf8')
if(!s.includes("const filtered=[...contextual.filter(row=>filter==='ALL'||row.displayKind===filter)].reverse()")){
  throw new Error('latest-first display patch missing')
}
if(!s.includes('niftyPointsFromEntry(currentNifty(report),entryNifty)')){
  throw new Error('Nifty delta is not computed from carried original entry')
}
if(!s.includes("entry?.price??entry?.entry_price??r.bar?.close")){
  throw new Error('entry Nifty source fallback missing')
}
console.log('PASS: latest-first rendering with entry-based Nifty delta source')
