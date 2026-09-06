/* Formula UI delegates evaluation/persistence to Fields; fixtures never touch live data. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const requests=[],timers=new Map();let sequence=0,saved=null,closed=0,hostWrites=0;
const nodes=new Map(),fieldButtons=[],operatorButtons=[];
function node(value=''){return {value,textContent:'',innerHTML:'',disabled:false,hidden:false,handlers:{},dataset:{},addEventListener(name,fn){this.handlers[name]=fn;},querySelectorAll(){return [];}};}
for(const key of ['name','type','decimals','expression','status','result','save','close','search','backspace','clear','constant','add-number'])nodes.set(`[data-formula-${key}]`,node(key==='type'?'number':key==='decimals'?'2':''));
const reports=[{id:'report',name:'Actual data',fields:[{id:'net',key:'Revenue',label:'Net',kind:'report',type:'number'},{id:'sold',key:'Sold',label:'Sold Leads',kind:'report',type:'number'},{id:'text',key:'Name',label:'Name',kind:'report',type:'text'}]}];
for(const field of reports[0].fields.filter(item=>item.type==='number')){const button=node();button.dataset.formulaField=field.id;button.textContent=field.label;fieldButtons.push(button);}
for(const operator of ['+','−','×','÷','(',')']){const button=node();button.dataset.formulaOperator=operator;operatorButtons.push(button);}
const host={set innerHTML(value){hostWrites++;this.markup=value;},querySelector:selector=>nodes.get(selector),querySelectorAll:selector=>selector==='[data-formula-field]'?fieldButtons:selector==='[data-formula-operator]'?operatorButtons:[...nodes.values(),...fieldButtons,...operatorButtons]};
const context=vm.createContext({window:{StatsSettings:{esc:String,json:(method,body)=>({method,body}),emit:()=>{},api:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))},StatsWidgetRenderer:{render:payload=>JSON.stringify(payload),fit:()=>{}}},AbortController,setTimeout:(fn)=>{timers.set(++sequence,fn);return sequence;},clearTimeout:id=>timers.delete(id)});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/settings/field-formulas.js'),'utf8'),context);
const editor=context.window.StatsFieldFormulas;
const flush=()=>{const callbacks=[...timers.values()];timers.clear();return Promise.all(callbacks.map(fn=>fn()));};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const payload={kind:'table',fields:[],rows:[{result:10}],unavailable_rows:0};
(async()=>{
  const dispose=editor.open({host,fieldId:'net',reports,onSaved:(field,catalog)=>{saved={field,catalog};},onClose:()=>closed++});
  assert.equal(hostWrites,1);assert.match(host.markup,/Each row/);assert.match(host.markup,/Name your result/);
  operatorButtons.find(button=>button.dataset.formulaOperator==='÷').handlers.click();
  fieldButtons[1].handlers.click();nodes.get('[data-formula-name]').value='Average Net';nodes.get('[data-formula-name]').handlers.input();
  const first=flush();assert.equal(requests.length,1);assert.equal(requests[0].options.body.formula,'[Revenue] ÷ [Sold]');assert.equal(requests[0].options.body.label,'Average Net');
  assert.equal(nodes.get('[data-formula-save]').disabled,true);requests[0].resolve({payload});await first;
  assert.equal(nodes.get('[data-formula-save]').disabled,false);assert.equal(hostWrites,1,'Results must not replace the field picker or inputs');
  // An obsolete evaluation must not re-enable saving a newer expression.
  nodes.get('[data-formula-type]').value='percent';nodes.get('[data-formula-type]').handlers.change();const old=flush();
  nodes.get('[data-formula-decimals]').value='3';nodes.get('[data-formula-decimals]').handlers.input();assert.equal(requests[1].options.signal.aborted,true);
  requests[1].resolve({payload});await old;assert.equal(nodes.get('[data-formula-save]').disabled,true);
  const current=flush();requests[2].resolve({payload});await current;assert.equal(nodes.get('[data-formula-save]').disabled,false);
  assert.equal(requests[2].options.body.percent_input_scale,'fraction');
  const saving=nodes.get('[data-formula-save]').onclick();assert.equal(requests[3].url,'/api/fields/report');assert.equal(requests[3].options.body.kind,'calculated');
  requests[3].resolve({field:{key:'created'}});await settle();assert.equal(requests[4].url,'/api/fields/catalog');
  requests[4].reject(new Error('Catalog unavailable'));await saving;
  assert.equal(nodes.get('[data-formula-name]').disabled,true,'A created formula cannot be edited while retrying its lookup');
  const retry=nodes.get('[data-formula-save]').onclick();assert.equal(requests[5].url,'/api/fields/catalog','Retry must not create a duplicate Field');
  requests[5].resolve({reports:[{id:'report',fields:[{id:'public-id',key:'created',label:'Average Net'}]}]});await retry;
  assert.equal(saved.field.id,'public-id');assert.equal(closed,0);dispose();
  assert.equal(editor.expression([{key:'immutable',label:'Renamed'},{value:'×'},{value:'2'}]),'[immutable] × 2');
  console.log('Inline Field formulas: named tokens, API-only math, debounce, cancellation, verified saves and public-ID return passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
