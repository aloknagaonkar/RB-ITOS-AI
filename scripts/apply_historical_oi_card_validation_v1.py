from pathlib import Path

UI = Path('frontend/src/historicalOiResearch.tsx')
CSS = Path('frontend/src/historicalOiResearch.css')
if not UI.exists():
    raise SystemExit('Safe-stop: historicalOiResearch.tsx not found.')

text = UI.read_text(encoding='utf-8')

helpers = r'''
type FieldState='AVAILABLE'|'DERIVED'|'SOURCE_MISSING'|'INCONSISTENT'
type ValidationItem={label:string;state:FieldState;detail:string}

const nearly=(a:any,b:any,tol=1e-6)=>{
  if(a==null||b==null)return false
  const x=Number(a),y=Number(b)
  return Number.isFinite(x)&&Number.isFinite(y)&&Math.abs(x-y)<=Math.max(tol,Math.abs(y)*1e-9)
}
const fstate=(v:any):FieldState=>v==null?'SOURCE_MISSING':'AVAILABLE'

function fixedValidation(row:Row):ValidationItem[]{
  const ceBase=row.fixed_ce_oi_baseline_0920
  const peBase=row.fixed_pe_oi_baseline_0920
  const ceNow=row.fixed_ce_oi
  const peNow=row.fixed_pe_oi
  const ceDelta=row.f_ce_delta
  const peDelta=row.f_pe_delta
  const imbalance=row.f_imbalance ?? (ceDelta!=null&&peDelta!=null?Number(peDelta)-Number(ceDelta):null)
  const basePcr=row.f_pcr_baseline ?? (ceBase!=null&&peBase!=null&&Number(ceBase)!==0?Number(peBase)/Number(ceBase):null)
  const currentPcr=row.f_pcr ?? (ceNow!=null&&peNow!=null&&Number(ceNow)!==0?Number(peNow)/Number(ceNow):null)
  const pcrChange=row.f_pcr_change ?? (basePcr!=null&&currentPcr!=null?Number(currentPcr)-Number(basePcr):null)
  const cePctExpected=ceBase!=null&&ceDelta!=null&&Number(ceBase)!==0?Number(ceDelta)/Number(ceBase)*100:null
  const pePctExpected=peBase!=null&&peDelta!=null&&Number(peBase)!==0?Number(peDelta)/Number(peBase)*100:null

  const out:ValidationItem[]=[
    {label:'Fixed strikes',state:fstate(row.fixed_strikes),detail:row.fixed_strikes?'Exact frozen 09:20 basket is present.':'Exact fixed strike identities are not present in this source.'},
    {label:'CE baseline OI',state:fstate(ceBase),detail:ceBase!=null?'09:20 CE baseline is present.':'CE baseline OI is not present in this source.'},
    {label:'PE baseline OI',state:fstate(peBase),detail:peBase!=null?'09:20 PE baseline is present.':'PE baseline OI is not present in this source.'},
    {label:'CE current OI',state:fstate(ceNow),detail:ceNow!=null?'Current fixed CE OI is present.':'Current fixed CE OI is not present in this source.'},
    {label:'PE current OI',state:fstate(peNow),detail:peNow!=null?'Current fixed PE OI is present.':'Current fixed PE OI is not present in this source.'},
  ]
  if(ceBase!=null&&ceNow!=null&&ceDelta!=null){
    out.push({label:'CE session ΔOI',state:nearly(Number(ceNow)-Number(ceBase),ceDelta)?'AVAILABLE':'INCONSISTENT',detail:`Expected ${signed(Number(ceNow)-Number(ceBase))}; source ${signed(ceDelta)}.`})
  }else out.push({label:'CE session ΔOI',state:ceDelta!=null?'AVAILABLE':'SOURCE_MISSING',detail:ceDelta!=null?'Stored ΔOI available; baseline/current pair unavailable for recomputation.':'CE session ΔOI missing.'})
  if(peBase!=null&&peNow!=null&&peDelta!=null){
    out.push({label:'PE session ΔOI',state:nearly(Number(peNow)-Number(peBase),peDelta)?'AVAILABLE':'INCONSISTENT',detail:`Expected ${signed(Number(peNow)-Number(peBase))}; source ${signed(peDelta)}.`})
  }else out.push({label:'PE session ΔOI',state:peDelta!=null?'AVAILABLE':'SOURCE_MISSING',detail:peDelta!=null?'Stored ΔOI available; baseline/current pair unavailable for recomputation.':'PE session ΔOI missing.'})

  out.push({label:'CE session %',state:row.f_ce_pct!=null?(cePctExpected==null?'AVAILABLE':nearly(row.f_ce_pct,cePctExpected)?'AVAILABLE':'INCONSISTENT'):(cePctExpected!=null?'DERIVED':'SOURCE_MISSING'),detail:row.f_ce_pct!=null?'Stored percentage available.':cePctExpected!=null?'Exactly derivable from baseline and ΔOI.':'CE baseline required.'})
  out.push({label:'PE session %',state:row.f_pe_pct!=null?(pePctExpected==null?'AVAILABLE':nearly(row.f_pe_pct,pePctExpected)?'AVAILABLE':'INCONSISTENT'):(pePctExpected!=null?'DERIVED':'SOURCE_MISSING'),detail:row.f_pe_pct!=null?'Stored percentage available.':pePctExpected!=null?'Exactly derivable from baseline and ΔOI.':'PE baseline required.'})
  out.push({label:'Session imbalance',state:row.f_imbalance!=null?'AVAILABLE':imbalance!=null?'DERIVED':'SOURCE_MISSING',detail:imbalance!=null?`PE ΔOI − CE ΔOI = ${signed(imbalance)}.`:'Both CE and PE session ΔOI required.'})
  out.push({label:'Baseline PCR',state:row.f_pcr_baseline!=null?'AVAILABLE':basePcr!=null?'DERIVED':'SOURCE_MISSING',detail:basePcr!=null?`PE baseline / CE baseline = ${n(basePcr,3)}.`:'Baseline CE and PE OI required.'})
  out.push({label:'Current PCR',state:row.f_pcr!=null?(currentPcr!=null&&nearly(row.f_pcr,currentPcr)?'AVAILABLE':'INCONSISTENT'):currentPcr!=null?'DERIVED':'SOURCE_MISSING',detail:currentPcr!=null?`PE current / CE current = ${n(currentPcr,3)}.`:'Current fixed CE and PE OI required.'})
  out.push({label:'PCR change',state:row.f_pcr_change!=null?'AVAILABLE':pcrChange!=null?'DERIVED':'SOURCE_MISSING',detail:pcrChange!=null?`Current PCR − baseline PCR = ${signed(pcrChange,3)}.`:'Baseline and current PCR required.'})
  return out
}

function movingValidation(row:Row):ValidationItem[]{
  const currentPcr=row.m_ce_oi!=null&&row.m_pe_oi!=null&&Number(row.m_ce_oi)!==0?Number(row.m_pe_oi)/Number(row.m_ce_oi):null
  const imbalance=row.m_ce_delta!=null&&row.m_pe_delta!=null?Number(row.m_pe_delta)-Number(row.m_ce_delta):null
  return [
    {label:'Current CE/PE OI',state:row.m_ce_oi!=null&&row.m_pe_oi!=null?'AVAILABLE':'SOURCE_MISSING',detail:'Both current moving-basket sides are required.'},
    {label:'Current PCR',state:row.m_pcr!=null?(currentPcr!=null&&nearly(row.m_pcr,currentPcr)?'AVAILABLE':'INCONSISTENT'):currentPcr!=null?'DERIVED':'SOURCE_MISSING',detail:currentPcr!=null?`PE / CE = ${n(currentPcr,3)}.`:'Current CE/PE OI unavailable.'},
    {label:'5m imbalance',state:imbalance!=null?'DERIVED':'SOURCE_MISSING',detail:imbalance!=null?`PE ΔOI − CE ΔOI = ${signed(imbalance)}.`:'5m CE/PE ΔOI required.'},
    {label:'5m PCR change',state:row.m_pcr_change!=null&&row.m_pcr_previous!=null&&row.m_pcr!=null?(nearly(Number(row.m_pcr)-Number(row.m_pcr_previous),row.m_pcr_change)?'AVAILABLE':'INCONSISTENT'):row.m_pcr_change!=null?'AVAILABLE':'SOURCE_MISSING',detail:'Checks current PCR minus previous same-strike PCR.'},
  ]
}

function ValidationBadge({items}:{items:ValidationItem[]}){
  const bad=items.filter(x=>x.state==='INCONSISTENT').length
  const missing=items.filter(x=>x.state==='SOURCE_MISSING').length
  const derived=items.filter(x=>x.state==='DERIVED').length
  const state=bad?'INCONSISTENT':missing?'PARTIAL':derived?'DERIVED_OK':'VALID'
  return <div className={`hoi-validation-summary hoi-validation-${state.toLowerCase()}`}><b>{state}</b><span>{items.length-bad-missing} usable · {derived} derived · {missing} source-missing · {bad} inconsistent</span></div>
}
'''

if 'function fixedValidation(' not in text:
    anchor='function Audit({row}:{row:Row}){'
    if anchor not in text: raise SystemExit('Safe-stop: Audit component anchor not found.')
    text=text.replace(anchor,helpers+'\n'+anchor,1)

# Extend Row type only if fields are absent.
if 'fixed_ce_oi_baseline_0920?:' not in text:
    marker='f_activity?:number|null;f_pcr:number|null;'
    extra='f_activity?:number|null;f_pcr:number|null;f_ce_pct?:number|null;f_pe_pct?:number|null;f_imbalance?:number|null;f_pcr_baseline?:number|null;f_pcr_change?:number|null;fixed_ce_oi_baseline_0920?:number|null;fixed_pe_oi_baseline_0920?:number|null;fixed_ce_oi?:number|null;fixed_pe_oi?:number|null;fixed_strikes?:string;fixed_complete?:boolean;'
    if marker in text: text=text.replace(marker,extra,1)

old_audit="function Audit({row}:{row:Row}){\n  const imbalance=(row.m_pe_delta==null||row.m_ce_delta==null)?null:row.m_pe_delta-row.m_ce_delta\n"
new_audit="""function Audit({row}:{row:Row}){\n  const imbalance=(row.m_pe_delta==null||row.m_ce_delta==null)?null:row.m_pe_delta-row.m_ce_delta\n  const fixedImbalance=row.f_imbalance ?? ((row.f_pe_delta!=null&&row.f_ce_delta!=null)?Number(row.f_pe_delta)-Number(row.f_ce_delta):null)\n  const fixedBasePcr=row.f_pcr_baseline ?? ((row.fixed_ce_oi_baseline_0920!=null&&row.fixed_pe_oi_baseline_0920!=null&&Number(row.fixed_ce_oi_baseline_0920)!==0)?Number(row.fixed_pe_oi_baseline_0920)/Number(row.fixed_ce_oi_baseline_0920):null)\n  const fixedCurrentPcr=row.f_pcr ?? ((row.fixed_ce_oi!=null&&row.fixed_pe_oi!=null&&Number(row.fixed_ce_oi)!==0)?Number(row.fixed_pe_oi)/Number(row.fixed_ce_oi):null)\n  const fixedPcrChange=row.f_pcr_change ?? ((fixedBasePcr!=null&&fixedCurrentPcr!=null)?Number(fixedCurrentPcr)-Number(fixedBasePcr):null)\n  const fixedCePct=row.f_ce_pct ?? ((row.fixed_ce_oi_baseline_0920!=null&&row.f_ce_delta!=null&&Number(row.fixed_ce_oi_baseline_0920)!==0)?Number(row.f_ce_delta)/Number(row.fixed_ce_oi_baseline_0920)*100:null)\n  const fixedPePct=row.f_pe_pct ?? ((row.fixed_pe_oi_baseline_0920!=null&&row.f_pe_delta!=null&&Number(row.fixed_pe_oi_baseline_0920)!==0)?Number(row.f_pe_delta)/Number(row.fixed_pe_oi_baseline_0920)*100:null)\n  const movingChecks=movingValidation(row)\n  const fixedChecks=fixedValidation(row)\n"""
if old_audit in text: text=text.replace(old_audit,new_audit,1)

if '<ValidationBadge items={movingChecks}/>' not in text:
    text=text.replace('<section><h4>Moving ATM OI</h4>','<section><h4>Moving ATM OI</h4><ValidationBadge items={movingChecks}/>',1)
if '<ValidationBadge items={fixedChecks}/>' not in text:
    for head in ('<section><h4>Fixed 09:20 ATM ±5</h4>','<section><h4>Fixed basket</h4>'):
        if head in text:
            text=text.replace(head,head.replace('</h4>','</h4><ValidationBadge items={fixedChecks}/>'),1)
            break

for a,b in {
  '{pct(row.f_ce_pct)}':'{pct(fixedCePct)}',
  '{pct(row.f_pe_pct)}':'{pct(fixedPePct)}',
  '{signed(row.f_imbalance)}':'{signed(fixedImbalance)}',
  '{n(row.f_pcr_baseline,3)}':'{n(fixedBasePcr,3)}',
  '{n(row.f_pcr,3)}':'{n(fixedCurrentPcr,3)}',
  '{signed(row.f_pcr_change,3)}':'{signed(fixedPcrChange,3)}',
}.items():
    text=text.replace(a,b)

note='<p className="hoi-audit-note">Forward returns are retrospective research labels and are not inputs to checkpoint classification.</p>'
block='''<div className="hoi-validation-details"><details><summary>Calculation/data validation</summary><div className="hoi-validation-list">{[...movingChecks,...fixedChecks].map((x,idx)=><div key={`${x.label}-${idx}`} className={`hoi-validation-row hoi-v-${x.state.toLowerCase()}`}><span>{x.label}</span><b>{x.state}</b><p>{x.detail}</p></div>)}</div></details></div>'''
if note in text and 'Calculation/data validation' not in text:
    text=text.replace(note,block+'\n    '+note,1)

UI.write_text(text,encoding='utf-8')

css=CSS.read_text(encoding='utf-8') if CSS.exists() else ''
rules='''\n.hoi-validation-summary{display:flex;gap:8px;align-items:center;margin:7px 0 10px;padding:6px 8px;border:1px solid #304753;border-radius:7px;font-size:.72rem}.hoi-validation-summary span{opacity:.68}.hoi-validation-summary b{font-size:.7rem;letter-spacing:.06em}.hoi-validation-partial{background:rgba(130,105,40,.08)}.hoi-validation-inconsistent{background:rgba(140,55,55,.10)}.hoi-validation-details{margin-top:10px;border-top:1px solid #29404c;padding-top:10px}.hoi-validation-details summary{cursor:pointer;font-weight:700}.hoi-validation-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:9px}.hoi-validation-row{border:1px solid #29404c;border-radius:8px;padding:8px;min-width:0}.hoi-validation-row span{display:block;font-size:.78rem}.hoi-validation-row b{display:block;margin:3px 0;font-size:.7rem;letter-spacing:.06em}.hoi-validation-row p{margin:0;opacity:.72;font-size:.74rem;overflow-wrap:anywhere}.hoi-v-inconsistent{background:rgba(140,55,55,.10)}.hoi-v-source_missing{background:rgba(130,105,40,.08)}@media(max-width:900px){.hoi-validation-list{grid-template-columns:1fr}}\n'''
if '.hoi-validation-summary' not in css: CSS.write_text(css.rstrip()+rules,encoding='utf-8')
print('Applied Historical OI Card Validation V1.')
