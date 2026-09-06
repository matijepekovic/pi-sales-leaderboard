/* Percentage meaning is declared once in Fields and shared by every renderer. */
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),context=vm.createContext({window:{StatsSettings:{esc:value=>String(value??""),on:()=>{}}}});
for(const file of ["app/static/runtime/field-values.js","app/static/settings/fields.js"]){vm.runInContext(fs.readFileSync(path.join(root,file),"utf8"),context);}
const values=context.window.StatsFieldValues,editor=context.window.StatsFieldEditor;
assert.equal(values.format(.99,"percent",1,"fraction"),"99.0%");
assert.equal(values.format(1.01,"percent",1,"fraction"),"101.0%");
assert.equal(values.percentRatio(1.01,"fraction"),1.01);
assert.equal(values.format(14.3,"percent",1,"points"),"14.3%");
assert.equal(values.format(.5,"percent",1,"points"),"0.5%");
assert.equal(values.format(1,"percent",0,"points"),"1%");
for(const scale of ["auto","fraction","points"]){
  assert.equal(values.format("101%","percent",1,scale),"101.0%");
  assert.equal(values.format(" 14.3% ","percent",1,scale),"14.3%");
  assert.equal(values.format(0,"percent",1,scale),"0.0%");
  assert.equal(values.format(null,"percent",1,scale),"0.0%");
  assert.equal(values.format("","percent",1,scale),"0.0%");
  assert.equal(values.format("unknown","percent",1,scale),"unknown");
  assert.equal(values.format(1.01,"number",2,scale),"1.01");
}
assert.equal(values.format(.99,"percent",1),"99.0%");
assert.equal(values.format(1.01,"percent",2),"1.01%");
assert.equal(values.format(14.3,"percent",1),"14.3%");
assert.ok(Number.isNaN(values.percentRatio(null,"fraction")));
const percentForm=editor.form("report",{key:"rate",type:"percent",source_type:"number",percent_input_scale:"fraction"});
assert.match(percentForm,/data-percent-input  style=/);
assert.match(percentForm,/value="fraction" selected/);
assert.match(percentForm,/0\.143 → 14\.3%/);
assert.match(percentForm,/14\.3 → 14\.3%/);
assert.match(editor.form("report",{key:"value",type:"number",source_type:"number"}),/data-percent-input hidden/);
let changed;
const choices={hidden:true},type={value:"number",closest:()=>({querySelector:()=>choices}),addEventListener:(_,handler)=>{changed=handler;}};
editor.bind({querySelectorAll:selector=>selector==="[data-field-type],[data-custom-type]"?[type]:[]});
type.value="percent";changed();assert.equal(choices.hidden,false);
type.value="number";changed();assert.equal(choices.hidden,true);
console.log("Percentage input scale: formatting, suffixes, legacy defaults and editor visibility passed.");
