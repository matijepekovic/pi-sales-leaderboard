/* Shared normalized Widget rendering. Source adapters and data evaluation stay upstream. */
(function(){
  const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const finite=(value,fallback=0)=>Number.isFinite(Number(value))?Number(value):fallback;
  const safeUrl=value=>{const url=String(value||"");return /^(\/[^/]|https?:\/\/|data:image\/(?:png|jpeg|webp|gif);)/i.test(url)?url:"";};
  function themeStyle(theme){
    return Object.entries(theme?.colors||{}).filter(([,value])=>/^#[0-9a-f]{6}$/i.test(String(value))).map(([key,value])=>`--widget-${key.replace(/_/g,"-")}:${value}`).join(";");
  }
  function cell(row,field){
    if((row?.__invalid_fields||[]).includes(field.key)||(field.kind==="calculated"&&row?.[field.key]===null))return '<span title="This calculation is unavailable">Unavailable</span>';
    const value=row?.[field.key],asset=safeUrl(row?.__field_assets?.[field.key]||(field.type==="asset"?value:""));
    return asset?`<img class="widget-field-asset" src="${esc(asset)}" alt="${field.type==="asset"?"":esc(value)}">`:esc(window.StatsFieldValues.format(value,field.type,field.decimals,field.percent_input_scale));
  }
  function table(section,theme,fit,editableFields){
    const fields=section.fields||[],limit=fit.rows?Math.max(1,Math.floor(finite(fit.rows,10))):Infinity,rows=(section.rows||[]).slice(0,limit);
    return `<div class="widget-table-viewport"><table class="widget-table"><thead><tr>${fields.map(field=>`<th title="${esc(field.label||field.key)}">${editableFields&&!field.instance_only?`<button class="widget-field-edit" type="button" data-widget-field-editor="${esc(field.id||field.key)}" title="${editableFields==="context"?"Column options for":"Edit"} ${esc(field.label||field.key)}${editableFields==="context"?"":" globally"}">${esc(field.label||field.key)}${editableFields==="context"?' <span aria-hidden="true">▾</span>':""}</button>`:esc(field.label||field.key)}</th>`).join("")}</tr></thead><tbody>${rows.map((row,index)=>{const asset=safeUrl(theme?.assets?.[index===0?"champion":"row"]);return `<tr${asset?` style="background-image:url('${esc(asset)}')"`:""}>${fields.map(field=>`<td title="${esc(row[field.key]??"")}">${cell(row,field)}</td>`).join("")}</tr>`;}).join("")||`<tr><td colspan="${Math.max(fields.length,1)}">No matching rows</td></tr>`}</tbody></table></div>`;
  }
  function render(section,{theme={},fit={},editableFields=false}={}){
    const refinement=theme.widget_styles?.[section.widget_id]||{};
    theme={...theme,colors:{...theme.colors,...refinement.colors}};
    const settings={...refinement,...(section.fit||{}),...fit},kind=section.kind||"table",error=section.error||"";
    return `<article class="stats-widget" data-widget-renderer data-widget-fit="${esc(JSON.stringify(settings))}" style="${themeStyle(theme)}"><header class="widget-heading"><strong>${esc(section.name||section.report_name||"Widget")}</strong></header>${error?`<div class="widget-empty widget-error">${esc(error)}</div>`:kind==="table"?table(section,theme,settings,editableFields):window.StatsWidgetCharts.render({...section,kind,inspectable:editableFields})}</article>`;
  }
  function fit(root){
    const nodes=[...(root.matches?.("[data-widget-renderer]")?[root]:[]),...root.querySelectorAll("[data-widget-renderer]")];
    nodes.forEach(node=>{
      const options=JSON.parse(node.dataset.widgetFit||"{}"),viewport=node.querySelector(".widget-table-viewport"),table=viewport?.querySelector("table");if(!table)return;
      const canvas=node.closest("[data-canvas-width]"),scale=canvas?canvas.clientWidth/Math.max(1,finite(canvas.dataset.canvasWidth,1920)):1;
      const rows=Math.max(1,finite(options.rows,table.tBodies[0]?.rows.length||1)),columns=Math.max(1,table.tHead?.rows[0]?.cells.length||1),height=Math.max(1,viewport.clientHeight),width=Math.max(1,viewport.clientWidth);
      const rowHeight=options.row_height?finite(options.row_height)*scale:height/(rows+1),font=options.font_size?finite(options.font_size)*scale:Math.min(rowHeight*.43,width/(columns*8)),padding=options.padding!==undefined&&options.padding!==null?finite(options.padding)*scale:Math.min(rowHeight*.12,8*scale);
      node.style.setProperty("--widget-row-height",`${Math.max(1,rowHeight)}px`);node.style.setProperty("--widget-font-size",`${Math.max(1,font)}px`);node.style.setProperty("--widget-padding",`${Math.max(0,padding)}px`);
    });
  }
  window.StatsWidgetRenderer=Object.freeze({render,fit,themeStyle,safeUrl});
})();
