/* Normalized Field display values shared by Settings previews and Display. */
(function(){
  function number(value){
    const raw=String(value??"").trim().replace(/[$,]/g,"");
    if(!raw)return NaN;
    return raw.endsWith("%")?Number(raw.slice(0,-1))/100:Number(raw);
  }
  function percentRatio(value,scale="auto"){
    const parsed=number(value);
    if(!Number.isFinite(parsed))return parsed;
    if(String(value).trim().endsWith("%"))return parsed;
    if(scale==="fraction")return parsed;
    if(scale==="points")return parsed/100;
    return Math.abs(parsed)<=1?parsed:parsed/100;
  }
  function format(value,type,decimals,scale="auto"){
    if(!["number","percent"].includes(type))return value===null||value===undefined?"":String(value);
    if(value===null||value===undefined||String(value).trim()==="")value=0;
    const places=Math.max(0,Math.min(8,Number.isFinite(Number(decimals))?Number(decimals):(type==="percent"?1:2)));
    let parsed=type==="percent"?percentRatio(value,scale)*100:number(value);
    if(!Number.isFinite(parsed))return String(value);
    return parsed.toLocaleString(undefined,{minimumFractionDigits:places,maximumFractionDigits:places})+(type==="percent"?"%":"");
  }
  window.StatsFieldValues=Object.freeze({number,percentRatio,format});
})();
