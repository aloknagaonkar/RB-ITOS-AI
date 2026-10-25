// VM-only deterministic scheduler checks. No browser, network or broker calls.
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('node:assert/strict');
const ts=require(path.resolve('frontend/node_modules/typescript'));
const source=fs.readFileSync('frontend/src/hilegaLivePolling.ts','utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const listeners={},timers=new Map();let id=0;
const window={setTimeout(fn,ms){timers.set(++id,{fn,ms});return id},clearTimeout(id){timers.delete(id)},
  addEventListener(k,fn){listeners[k]=fn},removeEventListener(k){delete listeners[k]}};
const document={hidden:false,addEventListener(k,fn){listeners[k]=fn},removeEventListener(k){delete listeners[k]}};
const box={exports:{},require:()=>({}),window,document,AbortController,Response,fetch:async()=>{throw Error('unexpected network')},console};
vm.runInNewContext(js,box);
const flush=async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve()};
(async()=>{
 let calls=0,release;
 const stop=box.exports.startLivePolling(async()=>{calls++;await new Promise(r=>release=r)},5000);
 assert.equal(calls,1);
 listeners.focus();assert.equal(calls,1,'focus must not overlap a request');
 release();await flush();assert.equal([...timers.values()][0].ms,0,'focus queues immediate refresh after current request');
 const next=[...timers.values()][0];timers.clear();next.fn();assert.equal(calls,2);
 release();await flush();stop();assert.equal(timers.size,0,'cleanup removes scheduled polls');
 assert.equal(Object.keys(listeners).length,0);
 document.hidden=true;calls=0;
 const stop2=box.exports.startLivePolling(async()=>{calls++},5000);
 assert.equal(calls,0);document.hidden=false;listeners.visibilitychange();await flush();assert.equal(calls,1);stop2();
 // A body transfer that hangs must be aborted by the timeout as well.
 box.fetch=async(_url,{signal})=>({status:200,statusText:'OK',headers:{},arrayBuffer:()=>new Promise((resolve,reject)=>{
   signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true})
 })});
 const request=box.exports.fetchLive('/local-test',undefined,25);await flush();
 const timer=[...timers.values()].find(t=>t.ms===25);assert.ok(timer);timer.fn();
 await assert.rejects(request,/aborted/);
 console.log('PASS: no overlapping polls, queued focus refresh, hidden-tab recovery, cleanup and body timeout');
})().catch(e=>{console.error(e);process.exitCode=1});
