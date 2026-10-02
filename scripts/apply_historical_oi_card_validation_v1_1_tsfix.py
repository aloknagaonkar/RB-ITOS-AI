from pathlib import Path

UI = Path('frontend/src/historicalOiResearch.tsx')
if not UI.exists():
    raise SystemExit('Safe-stop: frontend/src/historicalOiResearch.tsx not found.')

text = UI.read_text(encoding='utf-8')
anchor = "function Audit({row}:{row:Row}){\n  const imbalance=(row.m_pe_delta==null||row.m_ce_delta==null)?null:row.m_pe_delta-row.m_ce_delta\n"
insert = """function Audit({row}:{row:Row}){\n  const imbalance=(row.m_pe_delta==null||row.m_ce_delta==null)?null:row.m_pe_delta-row.m_ce_delta\n  const fixedImbalance=row.f_imbalance ?? ((row.f_pe_delta!=null&&row.f_ce_delta!=null)?Number(row.f_pe_delta)-Number(row.f_ce_delta):null)\n  const fixedBasePcr=row.f_pcr_baseline ?? ((row.fixed_ce_oi_baseline_0920!=null&&row.fixed_pe_oi_baseline_0920!=null&&Number(row.fixed_ce_oi_baseline_0920)!==0)?Number(row.fixed_pe_oi_baseline_0920)/Number(row.fixed_ce_oi_baseline_0920):null)\n  const fixedCurrentPcr=row.f_pcr ?? ((row.fixed_ce_oi!=null&&row.fixed_pe_oi!=null&&Number(row.fixed_ce_oi)!==0)?Number(row.fixed_pe_oi)/Number(row.fixed_ce_oi):null)\n  const fixedPcrChange=row.f_pcr_change ?? ((fixedBasePcr!=null&&fixedCurrentPcr!=null)?Number(fixedCurrentPcr)-Number(fixedBasePcr):null)\n  const fixedCePct=row.f_ce_pct ?? ((row.fixed_ce_oi_baseline_0920!=null&&row.f_ce_delta!=null&&Number(row.fixed_ce_oi_baseline_0920)!==0)?Number(row.f_ce_delta)/Number(row.fixed_ce_oi_baseline_0920)*100:null)\n  const fixedPePct=row.f_pe_pct ?? ((row.fixed_pe_oi_baseline_0920!=null&&row.f_pe_delta!=null&&Number(row.fixed_pe_oi_baseline_0920)!==0)?Number(row.f_pe_delta)/Number(row.fixed_pe_oi_baseline_0920)*100:null)\n  const movingChecks=movingValidation(row)\n  const fixedChecks=fixedValidation(row)\n"""

if 'const movingChecks=movingValidation(row)' in text:
    print('V1.1 TypeScript fix already present; no change required.')
elif anchor in text:
    text = text.replace(anchor, insert, 1)
    UI.write_text(text, encoding='utf-8')
    print('Applied Historical OI Card Validation V1.1 TypeScript scope fix.')
else:
    raise SystemExit('Safe-stop: Audit function anchor differs from expected source. Please show lines around function Audit.')
