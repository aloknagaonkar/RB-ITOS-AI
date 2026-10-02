from pathlib import Path
UI=Path("frontend/src/historicalOiResearch.tsx")
if not UI.exists(): raise SystemExit("Safe-stop: historicalOiResearch.tsx not found.")
text=UI.read_text(encoding="utf-8")

old="f_activity?:number|null;f_pcr:number|null;forward_5m_points?:number|null;"
new="f_activity?:number|null;f_pcr:number|null;f_ce_pct?:number|null;f_pe_pct?:number|null;f_imbalance?:number|null;f_pcr_baseline?:number|null;f_pcr_change?:number|null;fixed_ce_oi_baseline_0920?:number|null;fixed_pe_oi_baseline_0920?:number|null;fixed_ce_oi?:number|null;fixed_pe_oi?:number|null;fixed_strikes?:string;fixed_complete?:boolean;moving_horizons?:Record<string,any>;forward_5m_points?:number|null;"
if old in text: text=text.replace(old,new,1)

old_fixed='<section><h4>Fixed basket</h4><div><span>Fixed PCR</span><b>{n(row.f_pcr,3)}</b></div><div><span>Fixed CE ΔOI</span><b>{signed(row.f_ce_delta)}</b></div><div><span>Fixed PE ΔOI</span><b>{signed(row.f_pe_delta)}</b></div></section>'
new_fixed='''<section><h4>Fixed 09:20 ATM ±5</h4><div><span>Fixed strikes</span><b>{row.fixed_strikes||'—'}</b></div><div><span>CE baseline OI</span><b>{i(row.fixed_ce_oi_baseline_0920)}</b></div><div><span>PE baseline OI</span><b>{i(row.fixed_pe_oi_baseline_0920)}</b></div><div><span>CE current OI</span><b>{i(row.fixed_ce_oi)}</b></div><div><span>PE current OI</span><b>{i(row.fixed_pe_oi)}</b></div><div><span>CE session ΔOI</span><b>{signed(row.f_ce_delta)}</b></div><div><span>PE session ΔOI</span><b>{signed(row.f_pe_delta)}</b></div><div><span>CE session %</span><b>{pct(row.f_ce_pct)}</b></div><div><span>PE session %</span><b>{pct(row.f_pe_pct)}</b></div><div><span>Session imbalance</span><b>{signed(row.f_imbalance)}</b></div><div><span>Baseline PCR</span><b>{n(row.f_pcr_baseline,3)}</b></div><div><span>Current PCR</span><b>{n(row.f_pcr,3)}</b></div><div><span>PCR change</span><b>{signed(row.f_pcr_change,3)}</b></div></section>'''
if old_fixed in text: text=text.replace(old_fixed,new_fixed,1)

needle='<section><h4>Positioning</h4>'
horizons='''<section><h4>Moving same-strike 5m / 10m / 15m</h4>{[5,10,15].map(h=>{const x=row.moving_horizons?.[String(h)];return <div key={h} className="hoi-horizon-line"><span>{h}m</span><b>CE {signed(x?.ce_delta)} ({pct(x?.ce_pct)}) · PE {signed(x?.pe_delta)} ({pct(x?.pe_pct)}) · IMB {signed(x?.imbalance)} · PCR {n(x?.prior_pcr,3)} → {n(x?.current_pcr,3)} ({signed(x?.pcr_change,3)})</b></div>})}</section>'''
if "Moving same-strike 5m / 10m / 15m" not in text and needle in text:
    text=text.replace(needle,horizons+needle,1)

UI.write_text(text,encoding="utf-8")
print("Patched Historical OI audit UI calculations.")
