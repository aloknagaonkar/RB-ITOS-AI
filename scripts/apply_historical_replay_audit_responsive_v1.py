from pathlib import Path

CSS = Path('frontend/src/historicalReplay.css')
if not CSS.exists():
    raise SystemExit('Safe-stop: frontend/src/historicalReplay.css not found.')

text = CSS.read_text(encoding='utf-8')
marker = '/* HISTORICAL_REPLAY_AUDIT_RESPONSIVE_V1 */'
if marker in text:
    print('Historical Replay Audit Responsive V1 already applied.')
    raise SystemExit(0)

rules = r'''
/* HISTORICAL_REPLAY_AUDIT_RESPONSIVE_V1 */
.historical-replay,
.hr-table-wrap,
.hr-detail,
.hr-decision-audit {
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
}

/* Do not make the whole replay page horizontally draggable. */
.hr-table-wrap {
  overflow-x: hidden !important;
}

.hr-table {
  width: 100% !important;
  min-width: 0 !important;
  table-layout: fixed !important;
}

.hr-table th,
.hr-table td {
  min-width: 0 !important;
  overflow-wrap: anywhere;
  white-space: normal;
}

/* Keep the 10 checkpoint columns compact enough for a normal desktop viewport. */
.hr-table th:nth-child(1) { width: 6%; }
.hr-table th:nth-child(2) { width: 8%; }
.hr-table th:nth-child(3) { width: 7%; }
.hr-table th:nth-child(4),
.hr-table th:nth-child(5),
.hr-table th:nth-child(6) { width: 8%; }
.hr-table th:nth-child(7) { width: 12%; }
.hr-table th:nth-child(8) { width: 15%; }
.hr-table th:nth-child(9) { width: 11%; }
.hr-table th:nth-child(10) { width: 9%; }

/* Expanded audit must stay inside the selected row width. */
.hr-detail,
.hr-detail-grid,
.hr-horizons,
.hr-trade-summary,
.hr-terminal-panel,
.hr-lifecycle {
  width: 100%;
  min-width: 0 !important;
  max-width: 100%;
  overflow: hidden;
}

/* The decision audit was forcing horizontal scrolling because it had a 1050px min width. */
.hr-decision-table-wrap {
  width: 100%;
  max-width: 100%;
  overflow-x: hidden !important;
}

.hr-decision-table {
  width: 100% !important;
  min-width: 0 !important;
  max-width: 100% !important;
  table-layout: fixed !important;
  font-size: .78rem;
}

.hr-decision-table th,
.hr-decision-table td {
  min-width: 0 !important;
  white-space: normal !important;
  overflow-wrap: anywhere;
  word-break: normal;
  vertical-align: top;
}

/* Check / Role / Result stay narrow; narrative columns receive the space. */
.hr-decision-table th:nth-child(1),
.hr-decision-table td:nth-child(1) { width: 14%; }
.hr-decision-table th:nth-child(2),
.hr-decision-table td:nth-child(2) { width: 8%; }
.hr-decision-table th:nth-child(3),
.hr-decision-table td:nth-child(3) { width: 9%; }
.hr-decision-table th:nth-child(4),
.hr-decision-table td:nth-child(4) { width: 22%; }
.hr-decision-table th:nth-child(5),
.hr-decision-table td:nth-child(5) { width: 22%; }
.hr-decision-table th:nth-child(6),
.hr-decision-table td:nth-child(6) { width: 25%; }

.hr-decision-table code,
.hr-life-row code,
.hr-life-explain,
.hr-life-explain > div {
  min-width: 0;
  white-space: normal !important;
  overflow-wrap: anywhere;
}

@media (max-width: 1150px) {
  .hr-decision-table { font-size: .73rem; }
  .hr-decision-table th,
  .hr-decision-table td { padding: 7px 6px; }
  .hr-table { font-size: .76rem; }
  .hr-table th,
  .hr-table td { padding-left: 4px; padding-right: 4px; }
}
'''

CSS.write_text(text.rstrip() + '\n\n' + rules.strip() + '\n', encoding='utf-8')
print('Applied Historical Replay Audit Responsive V1.')
