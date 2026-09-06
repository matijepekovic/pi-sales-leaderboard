/* One working result and one contextual edit; all data uses isolated API fixtures. */
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const requests=[],timers=new Map(),root=path.resolve(__dirname,"..");let sequence=0;
const node=()=>({hidden:false,disabled:false,innerHTML:"",classList:{toggle:()=>{}},querySelector:()=>null,querySelectorAll:()=>[]});
const nodes={"[data-widget-panel]":node(),"[data-widget-preview]":node(),"[data-widget-toolbar]":node(),"[data-widget-formula-host]":node(),"[data-widget-global-editor]":node()};
const host={querySelector:selector=>nodes[selector]||null,querySelectorAll:()=>[],innerHTML:""};
const context=vm.createContext({window:{StatsSettings:{esc:value=>String(value??""),on:()=>{},emit:()=>{},json:(method,body)=>({method,body}),api:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))},StatsWidgetRenderer:{render:payload=>JSON.stringify(payload),fit:()=>{}}},document:{getElementById:()=>host},requestAnimationFrame:()=>{},setTimeout:callback=>{timers.set(++sequence,callback);return sequence;},clearTimeout:id=>timers.delete(id),AbortController,console,confirm:()=>true,alert:()=>{}});
vm.runInContext(fs.readFileSync(path.join(root,"app/static/runtime/field-values.js"),"utf8"),context);
const source=fs.readFileSync(path.join(root,"app/static/settings/widgets.js"),"utf8");
vm.runInContext(source.replace(/\}\)\(\);\s*$/,'window.builderTest={S,blank,normalize,setting,validation,saveError,definition,schedule,preview,change,chooseVisual,contextMarkup,previewMarkup,resultPayload,inspectPoint,filterDisplayValue,enteredFilterValue,action,panelMarkup,toolbarMarkup,visualOptions,editor,openColumn,openFormula,openGlobalField,updateColumn};})();'),context);
const B=context.window.builderTest,clone=value=>JSON.parse(JSON.stringify(value));
B.S.reports=[{id:"dataset",name:"Values",fields:[{id:"label",label:"Name",type:"text",kind:"report"},{id:"rate",label:"Close Rate",type:"percent",kind:"report"},{id:"amount",label:"Sold Leads",type:"number",kind:"report"},{id:"whole",label:"Pitched Leads",type:"number",kind:"report"},{id:"logo",label:"Logo",type:"asset",kind:"group"},{id:"rank",label:"Rank",type:"number",kind:"table"}]}];
function draft(kind="table",ids=["rate","label"]){B.S.draft=B.blank();B.S.draft.kind=kind;B.S.draft.field_ids=ids;B.S.draft.chart.measure_field_ids=ids.filter(id=>["rate","amount","whole"].includes(id));Object.assign(B.S,{verified:null,payload:null,inspectionPayload:null,previewError:"",loading:false,history:[],panel:null,saving:false,dataView:false});timers.clear();}
function verified(){B.S.payload={kind:B.S.draft.kind,name:"Verified result",fields:[],total_rows:2,rows:[{label:"Alex",amount:10},{label:"Blair",amount:20}]};B.S.verified=clone(B.S.draft);}
function flush(){const pending=[...timers.values()];timers.clear();return Promise.all(pending.map(callback=>callback()));}
const answer=(request,extra={})=>request.resolve({payload:{kind:B.S.draft.kind,name:"Fresh result",fields:[],rows:[{label:"Alex",amount:10},{label:"Blair",amount:20}],total_rows:2,...extra}});
draft("table",["rate","label","logo","rank"]);verified();
assert.equal((B.editor().match(/data-widget-preview aria-live/g)||[]).length,1,"There is one result slot");
for(const removed of ["Prepared chart values","data-widget-intent","data-widget-outcomes","widget-calculation-option","data-widget-underlying"])assert.ok(!B.editor().includes(removed));
assert.match(B.previewMarkup(),/Alex/);assert.match(B.toolbarMarkup(),/Show as: Table/);
assert.deepEqual(clone(B.visualOptions()).map(item=>item[0]),["table","bar","line","percentage"]);
B.openColumn("rate");assert.equal(requests.length,0,"Opening a column does not request calculation previews");
assert.equal(B.S.panel.kind,"column");assert.match(B.panelMarkup(),/>Calculate</);assert.doesNotMatch(B.panelMarkup(),/value="sum"/);
B.openColumn("logo");assert.doesNotMatch(B.panelMarkup(),/>Calculate</);assert.doesNotMatch(B.panelMarkup(),/data-widget-measure/);
B.openColumn("rank");assert.doesNotMatch(B.panelMarkup(),/Use as labels/);
const before=clone(B.S.draft);B.openColumn("amount");assert.deepEqual(clone(B.S.draft),before,"An unselected column cannot change the draft");

draft("bar",["amount","whole","label"]);
B.S.draft.chart.measure_settings.amount={aggregation:"ratio",denominator_field_id:"whole",ratio_mode:"totals",result_type:"number"};
B.S.draft.chart.measure_settings.whole={aggregation:"average"};
const original=clone(B.S.draft);B.chooseVisual("pie");assert.deepEqual(clone(B.S.draft),original);assert.match(B.S.panel.question,/same whole/);
B.chooseVisual("pie",true);assert.deepEqual(clone(B.S.draft.chart.measure_settings),original.chart.measure_settings);
B.chooseVisual("table");assert.deepEqual(clone(B.S.draft.chart.measure_settings),original.chart.measure_settings,"Table retains dormant chart calculations");
const legacy=B.normalize({...original,chart:{aggregation:"ratio",measure_field_ids:["amount"],denominator_field_id:"whole",ratio_mode:"row_average",result_type:"number"}});
assert.equal(B.setting("amount",legacy).ratio_mode,"row_average");assert.equal(legacy.chart.layout,"shared");
draft("bar",["amount","whole"]);B.S.draft.chart.measure_field_ids=["amount"];B.S.draft.chart.measure_settings.amount={aggregation:"sum"};
B.chooseVisual("pie");assert.equal(B.S.panel.blocked,true);assert.ok(!clone(B.visualOptions()).some(item=>item[0]==="pie"));
draft("bar",["rate"]);B.S.draft.chart.measure_field_ids=["rate"];B.S.draft.chart.measure_settings.rate={aggregation:"sum"};assert.match(B.validation(),/cannot be added/);
draft("bar",["label"]);B.S.draft.chart.measure_field_ids=["label"];assert.match(B.validation(),/not numeric/);B.S.draft.chart.measure_settings.label={aggregation:"count"};assert.equal(B.validation(),"");
draft("table",["amount","whole","label"]);B.chooseVisual("line");assert.match(B.panelMarkup(),/Date or sequence Field/);assert.match(B.panelMarkup(),/data-widget-order/);
B.chooseVisual("line",true);assert.equal(B.S.draft.kind,"table");
B.S.draft.chart.dimension_field_id="label";B.S.draft.chart.category_order="date";B.chooseVisual("line",true);assert.equal(B.S.draft.kind,"line");
B.chooseVisual("bar");assert.equal(B.S.draft.chart.category_order,"date");
const rule={field_id:"rate",operator:"greater_than",value:.5};assert.equal(B.filterDisplayValue(rule),"50%");assert.equal(B.enteredFilterValue(rule,"0.5"),"0.5%");assert.equal(rule.value,.5);

(async()=>{
  // A selected summary updates the existing chart through one normal preview.
  draft("bar",["amount","whole","label"]);verified();const start=requests.length;
  B.openColumn("amount");assert.equal(requests.length,start);B.updateColumn("aggregation","sum");assert.equal(timers.size,1);
  const pending=flush(),old=requests.at(-1);assert.equal(requests.length,start+1);
  assert.equal(old.options.body.widget.chart.measure_settings.amount.aggregation,"sum");assert.equal(B.S.payload.name,"Verified result");assert.match(B.saveError(),/Wait/);
  B.updateColumn("aggregation","average");assert.equal(old.options.signal.aborted,true);
  answer(old,{name:"Obsolete"});await pending;assert.equal(B.S.payload.name,"Verified result");
  const current=flush();answer(requests.at(-1));await current;assert.equal(B.S.payload.name,"Fresh result");assert.equal(B.saveError(),"");
  B.updateColumn("aggregation","ratio");assert.equal(timers.size,0,"Do not guess a divisor or request meaningless ratios");assert.match(B.saveError(),/divide by/);
  B.updateColumn("denominator_field_id","whole");assert.equal(B.setting("amount").ratio_mode,"totals");
  B.updateColumn("ratio_mode","row_average");B.updateColumn("result_type","percent");
  assert.equal(timers.size,1);const ratio=flush();assert.equal(requests.at(-1).options.body.widget.chart.measure_settings.amount.result_type,"percent");answer(requests.at(-1));await ratio;
  B.updateColumn("ratio_mode","individual");const individual=flush();answer(requests.at(-1));await individual;
  assert.equal(B.setting("amount").ratio_mode,"individual");
  const configured=clone(B.S.draft);await B.action({dataset:{widgetAction:"data-view"}});assert.equal(B.resultPayload().kind,"table");assert.deepEqual(clone(B.S.draft),configured,"View data does not change the saved visual");
  assert.match(B.toolbarMarkup(),/Back to chart/);await B.action({dataset:{widgetAction:"data-view"}});assert.equal(B.resultPayload().kind,"bar");
  context.window.StatsWidgetCharts={inspect:()=>({kind:"table",name:"Contributors",rows:[{label:"Blair"}],total_rows:1})};
  B.inspectPoint({});assert.equal(B.resultPayload().name,"Contributors");await B.action({dataset:{widgetAction:"data-view"}});assert.equal(B.resultPayload().kind,"bar");
  // New edits keep the prior verified result until the exact definition passes.
  B.openColumn("amount");B.updateColumn("aggregation","sum");const failed=flush();requests.at(-1).reject(new Error("Invalid values"));await failed;
  assert.equal(B.S.payload.name,"Fresh result");assert.match(B.saveError(),/Invalid values/);
  const requestCount=requests.length;await B.action({dataset:{widgetAction:"save"}});assert.equal(requests.length,requestCount);
  await B.action({dataset:{widgetAction:"cancel-pending"}});const restore=flush();answer(requests.at(-1));await restore;assert.equal(B.saveError(),"");
  await B.action({dataset:{widgetAction:"undo"}});assert.equal(timers.size,1);

  // All contextual tools replace each other. Detached callbacks cannot close a new editor.
  draft("table",["amount","whole","label"]);verified();let disposed=0,formulaOptions,globalOptions;
  context.window.StatsFieldFormulas={open:options=>{formulaOptions=options;return ()=>{disposed++;};}};
  context.window.StatsFieldEditor={openById:(id,reports,container,options)=>{globalOptions=options;}};
  B.openColumn("amount");await B.action({dataset:{widgetAction:"calculate",id:"amount"}});
  assert.equal(B.S.panel.kind,"formula");assert.equal(nodes["[data-widget-preview]"].hidden,true);assert.match(B.saveError(),/Field edit/);
  await B.action({dataset:{widgetAction:"filters"}});assert.equal(disposed,1);assert.equal(B.S.panel.kind,"filters");assert.equal(nodes["[data-widget-preview]"].hidden,false);
  assert.doesNotMatch(B.panelMarkup(),/data-widget-formula-host/);
  B.openGlobalField("amount");assert.equal(B.S.panel.kind,"global");assert.match(B.panelMarkup(),/data-widget-action="dismiss-panel"/);
  B.openColumn("whole");globalOptions.onClose();assert.equal(B.S.panel.id,"whole");
  const savedGlobal=globalOptions.onSaved();requests.at(-1).resolve({reports:clone(B.S.reports)});await savedGlobal;assert.equal(B.S.panel.id,"whole");
  B.openFormula("amount");const lateFormula=formulaOptions;B.openColumn("whole");const unchanged=clone(B.S.draft);
  await lateFormula.onSaved({id:"late-field"},clone(B.S.reports));assert.equal(B.S.panel.id,"whole");assert.deepEqual(clone(B.S.draft),unchanged);
  lateFormula.onClose();assert.equal(B.S.panel.id,"whole","A detached formula cannot dismiss the newer edit");
  B.openFormula("amount");formulaOptions.onClose();assert.equal(B.S.panel,null);assert.equal(nodes["[data-widget-preview]"].hidden,false);
  draft("bar",["amount"]);B.openColumn("amount");B.updateColumn("aggregation","off");
  B.chooseVisual("table");assert.deepEqual(clone(B.S.draft.chart.measure_field_ids),[]);B.chooseVisual("bar");
  assert.deepEqual(clone(B.S.draft.chart.measure_field_ids),[]);assert.equal(B.S.draft.kind,"table");
  assert.deepEqual(clone(B.normalize(B.S.draft).chart.measure_field_ids),[],"An explicit empty chart selection stays empty after reopening");
  console.log("Simple Widget builder: one result, contextual edits, single preview request, preserved math, stale guards and owner isolation passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});
