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
const {eventKind,pathText,computedPremiumPoints,decisionText}=moduleBox.exports
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
assert.match(decisionText(r({transitions:[{event_type:'ENTRY_OPENING_BULLISH_CONFIRMED'}]})),/entry signal/i)
console.log('PASS: Hilega shared decision/CE contract assertions')
