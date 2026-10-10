const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const ts=require(path.resolve('frontend/node_modules/typescript'));const source=fs.readFileSync('frontend/src/hilegaReplayPerformance.ts','utf8');const mod={exports:{}};
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,{exports:mod.exports,module:mod,Map});
const merge=mod.exports.replayPerformance,day='2026-10-06';
const base={session_date:day,performance_summary:['LIVE_RECORDED_V1','HILEGA_V1_REPLAY','HILEGA_WMA_GAP_V2_REPLAY'].map((strategy_id,i)=>({strategy_id,available:true,net_points:100+i}))};
const tested={session_date:day,performance_summary:[{strategy_id:'HILEGA_V2_ALIGNMENT_DUAL_EXIT_REPLAY_V1',available:true,net_points:-50.7}],reports:[{checkpoint:'unchanged'}]};
for(const selected of [base,tested]){const x=merge(day,selected,base,tested,'','');assert.strictEqual(x.length,4);assert(x.every(r=>r.available));assert.strictEqual(x[3].net_points,-50.7);assert.strictEqual(x[0].net_points,100);}
assert.strictEqual(tested.reports[0].checkpoint,'unchanged');
const failed=merge(day,tested,null,null,'No canonical evidence','');assert.strictEqual(failed[0].available,false);assert.strictEqual(failed[0].unavailable_reason,'No canonical evidence');assert.strictEqual(failed[3].net_points,-50.7);
const other=merge(day,tested,{...base,session_date:'2026-10-07'},null,'','');assert.strictEqual(other[0].available,false);
const override=merge(day,{...base,performance_summary:[{strategy_id:'LIVE_RECORDED_V1',available:true,net_points:777}]},base,tested,'','');assert.strictEqual(override[0].net_points,777);
const zero=merge(day,{...tested,performance_summary:[{...tested.performance_summary[0],net_points:0,gain_loss_ratio:null,available:true}]},base,null,'','');assert.strictEqual(zero[3].available,true);assert.strictEqual(zero[3].net_points,0);
console.log('PASS: four-strategy population for every selection, missing-data labels, same-date isolation, selected metric precedence and zero-trade availability');
