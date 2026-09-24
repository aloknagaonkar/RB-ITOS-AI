/* Standalone contract tests for the shared view's pure classification/economics.
   Run from the repository root after frontend dependencies are installed:
   node tests/test_hilega_decision_table_v1.cjs
*/
const assert=require('node:assert/strict')
const fs=require('node:fs')
const path=require('node:path')
const repo=path.resolve(__dirname,'..')
const ts=require(path.join(repo,'frontend/node_modules/typescript'))
const source=fs.readFileSync(path.join(repo,'frontend/src/hilegaDecisionTable.tsx'),'utf8')
const out=ts.transpileModule(source,{fileName:'hilegaDecisionTable.tsx',reportDiagnostics:true,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}})
assert.deepEqual((out.diagnostics??[]).filter(d=>d.category===ts.DiagnosticCategory.Error),[], 'TypeScript syntax')
const moduleBox={exports:{}}
const mockRequire=name=>name==='react'?{useMemo:()=>{},useState:()=>{},Fragment:Symbol('Fragment')}:name==='react/jsx-runtime'?{jsx:()=>{},jsxs:()=>{}}:name.endsWith('.css')?{}:require(name)
new Function('require','module','exports',out.outputText)(mockRequire,moduleBox,moduleBox.exports)
const {eventKind,pathText,computedPremiumPoints,decisionText,deriveDecisionRows,displayDecisionText}=moduleBox.exports
const r=(over={})=>({checkpoint:'2026-09-23T09:35:00+05:30',transitions:[],strategy:{state_before:'PATH1_IDLE',state_after:'PATH1_IDLE',events_emitted:[]},route_a:{},route_b:{},...over})
assert.equal(eventKind(r({transitions:[{event_type:'ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21'}]})),'ENTRY')
assert.equal(eventKind(r({transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'}]})),'EXIT')
assert.equal(eventKind(r({strategy:{events_emitted:['PATH1_ARMED_RSI_CROSS_EMA3_UP']}})),'DETECTED')
assert.equal(eventKind(r({strategy:{events_emitted:['OPENING_REJECTED_0920']}})),'REJECTED')
assert.equal(eventKind(r({strategy:{state_before:'BULLISH_ACTIVE',state_after:'BULLISH_ACTIVE',events_emitted:[]}})),'ACTIVE')
assert.equal(eventKind(r()),'NONE')
assert.equal(pathText(r({strategy:{state_before:'OPENING_CANDIDATE',state_after:'OPENING_HOLD',events_emitted:[]}})),'Opening path')
assert.equal(computedPremiumPoints({entry_open:100,exit_open:112.5,exit_timestamp:'2026-09-23T10:00:00+05:30'}),12.5)
assert.equal(computedPremiumPoints({entry_open:100,exit_open:null,exit_timestamp:null}),null)
assert.equal(computedPremiumPoints({entry_open:100,exit_open:90,exit_timestamp:'2026-09-23T10:00:00+05:30'}),-10)
assert.equal(decisionText(r({transitions:[{event_type:'ENTRY_OPENING_BULLISH_CONFIRMED'}]})),'BULLISH_ENTRY')
assert.equal(decisionText(r({strategy:{state_before:'BULLISH_ACTIVE',state_after:'BULLISH_ACTIVE',events_emitted:[]}})),'BULLISH_CONTINUATION')
assert.equal(decisionText(r({transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'}]})),'BULLISH_EXIT')
const session=deriveDecisionRows([
  r({checkpoint:'2026-09-23T09:35:00+05:30',transitions:[{event_type:'ENTRY_PATH1_ROUTE_B_STRUCTURAL'}],strategy:{state_before:'PATH1_ARMED',state_after:'BULLISH_ACTIVE',selected_route:'ROUTE_B'}}),
  r({checkpoint:'2026-09-23T09:40:00+05:30',strategy:{state_before:'BULLISH_ACTIVE',state_after:'BULLISH_ACTIVE'}}),
  r({checkpoint:'2026-09-23T09:45:00+05:30',transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21',details:{original_entry_time:'2026-09-23T09:35:00+05:30'}}],strategy:{state_before:'BULLISH_ACTIVE',state_after:'PATH1_IDLE'}}),
  r({checkpoint:'2026-09-23T09:50:00+05:30',strategy:{state_before:'PATH1_IDLE',state_after:'PATH1_IDLE'}})
])
assert.equal(session[0].displayKind,'ENTRY')
assert.equal(session[1].displayKind,'ACTIVE')
assert.equal(session[1].origin,session[0].report.checkpoint)
assert.equal(session[1].originRoute,'ROUTE B')
assert.equal(session[2].displayKind,'EXIT')
assert.equal(session[2].origin,session[0].report.checkpoint)
assert.equal(session[3].displayKind,'NONE')
assert.equal(session[3].origin,null)
assert.equal(session[3].originRoute,null)

// Orphan raw exit/continuation records must not become valid bullish lifecycle labels.
const orphan=deriveDecisionRows([
  r({checkpoint:'2026-09-23T09:30:00+05:30'}),
  r({checkpoint:'2026-09-23T09:40:00+05:30',transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'}],strategy:{state_before:'PATH1_IDLE',state_after:'PATH1_IDLE',selected_route:'ROUTE_A'}}),
  r({checkpoint:'2026-09-23T09:45:00+05:30',strategy:{state_before:'BULLISH_ACTIVE',state_after:'BULLISH_ACTIVE'}})
])
assert.equal(orphan[1].displayKind,'REVIEW')
assert.equal(orphan[1].lifecycleIssue,'EXIT_WITHOUT_BULLISH_ENTRY')
assert.equal(orphan[2].displayKind,'REVIEW')
assert.equal(orphan[2].lifecycleIssue,'CONTINUATION_WITHOUT_BULLISH_ENTRY')
assert.equal(displayDecisionText(orphan[1].displayKind),'REVIEW_REQUIRED')

// Once entered, ordinary completed candles remain continuation until the exit.
const carried=deriveDecisionRows([
  r({checkpoint:'2026-09-23T10:00:00+05:30',transitions:[{event_type:'ENTRY_OPENING_BULLISH_CONFIRMED'}],strategy:{state_before:'OPENING_HOLD',state_after:'BULLISH_ACTIVE',selected_route:'OPENING_PATH'}}),
  r({checkpoint:'2026-09-23T10:05:00+05:30',strategy:{state_before:'BULLISH_ACTIVE',state_after:'PATH1_IDLE',events_emitted:['OPENING_REJECTED_0920']}}),
  r({checkpoint:'2026-09-23T10:10:00+05:30',transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'}],strategy:{state_before:'BULLISH_ACTIVE',state_after:'PATH1_IDLE'}})
])
assert.equal(carried[1].displayKind,'ACTIVE')
assert.equal(carried[1].originRoute,'OPENING PATH')
assert.equal(carried[2].displayKind,'EXIT')

// Explicit linkage can validate an exit when the loaded live window begins after entry.
const linkedExit=deriveDecisionRows([
  r({checkpoint:'2026-09-23T11:00:00+05:30',linked_signal_bar:'2026-09-23T10:30:00+05:30',transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'}],strategy:{state_before:'BULLISH_ACTIVE',state_after:'PATH1_IDLE',selected_route:'ROUTE_B'}})
])
assert.equal(linkedExit[0].displayKind,'EXIT')
assert.equal(linkedExit[0].origin,'2026-09-23T10:30:00+05:30')
console.log('PASS: Hilega lifecycle-consistent decision/CE contract assertions')
