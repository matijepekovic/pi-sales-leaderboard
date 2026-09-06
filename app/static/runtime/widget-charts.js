/* Chart geometry consumes evaluated Widget values, never rows or source adapters. */
(function(){
  const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const hasValue=value=>value!==null&&value!==undefined&&value!==""&&Number.isFinite(Number(value));
  const palette=["var(--widget-primary)","var(--widget-secondary)","var(--widget-primary-bright)","var(--widget-muted)","var(--widget-primary-dark)"];
  const color=index=>palette[index%palette.length];
  const empty=text=>`<div class="widget-empty">${esc(text)}</div>`;
  const point=(section,index,series=0)=>section.inspectable?` data-chart-point="${index}" data-chart-series="${series}" role="button" tabindex="0" aria-label="Inspect contributing data"`:"";
  function legend(items){
    return `<div class="widget-legend">${items.map((item,index)=>`<span><i style="background:${item.color||color(index)}"></i>${esc(item.label??item)}</span>`).join("")}</div>`;
  }
  function contract(section){
    const data=section.chart||{},metadata=new Map([...(section.fields||[]),...(section.calculation_fields||[])].map(field=>[field.id||field.key,field]));
    const settingsFor=(item,index)=>item.value_settings?.[index]||data.measure_settings?.[data.value_field_ids?.[index]||item.field_id]||{aggregation:item.aggregation||data.aggregation,ratio_mode:item.ratio_mode||data.ratio_mode};
    const fieldFor=(item,index)=>item.value_formats?.[index]||item.value_format||(data.aggregation==="ratio"?{type:data.value_type||"percent",decimals:1}:data.aggregation==="count"?{type:"number",decimals:0}:metadata.get(data.value_field_ids?.[index]||item.field_id))||{type:"number",decimals:2};
    // Evaluated percentages have a declared scale. Never reinterpret a 120% ratio as 1.2%.
    const formatField=(value,field)=>{
      if(!hasValue(value))return "Unavailable";
      if(field.type==="percent"&&(data.percentage_scale==="fraction"||data.measure_settings))return window.StatsFieldValues.format(Number(value)*100,"number",field.decimals??1)+"%";
      return window.StatsFieldValues.format(value,field.type,field.decimals,field.percent_input_scale);
    };
    const detail=(value,item,index)=>{
      const result=formatField(value,fieldFor(item,index)),settings=settingsFor(item,index),reason=item.reasons?.[index];
      if(reason)return `${result} · ${reason}`;
      if(settings.aggregation!=="ratio")return result;
      if(settings.ratio_mode==="row_average")return `${result} · average of ${item.sample_counts?.[index]??0} individual row ratios`;
      const numerator=item.numerators?.[index],denominator=item.denominators?.[index];
      const a=metadata.get(data.value_field_ids?.[index]||item.field_id||data.numerator_field_id)||{type:"number",decimals:2},b=metadata.get(settings.denominator_field_id||data.denominator_field_id)||{type:"number",decimals:2};
      return `${result} (${formatField(numerator,a)} / ${formatField(denominator,b)})`;
    };
    return {data,metadata,fieldFor,formatField,detail,format:(value,item,index)=>formatField(value,fieldFor(item,index))};
  }
  function context(c){
    const label=c.data.aggregation_label;
    if(!label)return "";
    const rows=c.data.source_row_count,counts=c.data.series.flatMap(item=>item.sample_counts||[]);
    const min=counts.length?Math.min(...counts):null,max=counts.length?Math.max(...counts):null;
    const samples=min===null?"":` · ${min===max?min:`${min}–${max}`} contributing ${min===max&&min===1?"row":"rows"}${counts.length>1?" per result":""}`;
    return `<div class="widget-chart-context">${esc(label)}${Number.isFinite(rows)?` · ${rows} matching ${rows===1?"row":"rows"}`:""}${esc(samples)}</div>`;
  }
  function percentage(section,c){
    const fraction=c.data.fraction,item=c.data.series[0],value=item.values[0],field=c.fieldFor(item,0);
    if(!hasValue(fraction))return empty(item.reasons?.[0]||"No percentage data");
    if(fraction<0||fraction>1)return empty("A percentage circle requires a value from 0% to 100%.");
    const percent=Number(fraction)*100,label=c.data.categories[0],formatted=c.formatField(value,field);
    const remainder=window.StatsFieldValues.format(100-percent,"number",field.decimals??1)+"%";
    const title=`${label}: ${c.detail(value,item,0)}; remainder to 100%: ${remainder}`;
    return `<div class="widget-chart widget-percentage"><svg viewBox="0 0 800 400" role="img" aria-label="${esc(title)}"><title>${esc(title)}</title><g${point(section,0)}><circle class="widget-percentage-track" cx="400" cy="180" r="130" fill="none" stroke="var(--widget-muted)" stroke-opacity=".22" stroke-width="36"/>${fraction>0?`<circle class="widget-percentage-value" cx="400" cy="180" r="130" fill="none" stroke="${color(0)}" stroke-width="36" pathLength="100" stroke-dasharray="${percent} ${100-percent}" transform="rotate(-90 400 180)"/>`:""}<text class="widget-percentage-number" x="400" y="183" text-anchor="middle">${esc(formatted)}</text><text x="400" y="212" text-anchor="middle">out of 100%</text><text class="widget-percentage-label" x="400" y="367" text-anchor="middle">${esc(label)}</text></g></svg>${legend([{label:`${label} · ${c.detail(value,item,0)}`},{label:`Remainder to 100% · ${remainder}`,color:"var(--widget-muted)"}])}</div>`;
  }
  function composition(section,c){
    const {categories,series}=c.data,item=series[0],values=item.values||[];
    if(values.some(value=>!hasValue(value)))return empty("A value is unavailable. A partial pie would misrepresent the total.");
    if(values.some(value=>hasValue(value)&&Number(value)<0))return empty("Pie charts cannot show negative values.");
    const sum=values.reduce((total,value)=>total+(hasValue(value)?Number(value):0),0);
    if(!Number.isFinite(sum))return empty("Chart values exceed the supported numeric range.");
    if(!sum)return empty("No positive values for this pie chart");
    let angle=-Math.PI/2;
    const entries=categories.map((label,index)=>{
      const value=values[index],fraction=hasValue(value)?Number(value)/sum:0;
      const share=window.StatsFieldValues.format(fraction*100,"number",1)+"% of total";
      return {label:`${label}: ${c.format(value,item,index)}${hasValue(value)?` · ${share}`:""}`,fraction};
    });
    const slices=entries.map((entry,index)=>{
      if(!entry.fraction)return "";
      const next=angle+entry.fraction*Math.PI*2,coordinate=a=>[400+148*Math.cos(a),180+148*Math.sin(a)],a=coordinate(angle),b=coordinate(next);angle=next;
      return entry.fraction>=1?`<circle cx="400" cy="180" r="148" fill="${color(index)}"${point(section,index)}><title>${esc(entry.label)}</title></circle>`:`<path d="M400 180 L${a.join(" ")} A148 148 0 ${entry.fraction>.5?1:0} 1 ${b.join(" ")} Z" fill="${color(index)}" stroke="var(--widget-panel)" stroke-width="2"${point(section,index)}><title>${esc(entry.label)}</title></path>`;
    }).join("");
    return `<div class="widget-chart"><svg viewBox="0 0 800 400" role="img" aria-label="${esc(section.name||"Parts of total")}">${slices}</svg>${legend(entries)}</div>`;
  }
  function cartesian(section,c){
    const {categories,series}=c.data,measured=series.flatMap(item=>(item.values||[]).map((value,index)=>c.fieldFor(item,index)));
    const sameType=measured.length&&measured.every(field=>field.type===measured[0].type);
    const axisField=sameType?{type:measured[0].type,decimals:Math.max(...measured.map(field=>Number.isFinite(Number(field.decimals))?Number(field.decimals):2))}:{type:"number",decimals:2};
    const width=800,height=400,left=82,top=28,bottom=322,right=765,plotWidth=right-left,plotHeight=bottom-top;
    const values=series.flatMap(item=>(item.values||[]).filter(hasValue).map(Number));
    if(!values.length)return empty(series.flatMap(item=>item.reasons||[]).find(Boolean)||"No chart data");
    // Rates use an honest 0–100% reference, extending only for values outside it.
    const percentAxis=axisField.type==="percent",min=Math.min(0,...values);
    let max=Math.max(percentAxis?1:0,...values)||1;
    if(c.data.aggregation==="count")max=Math.max(4,Math.ceil(max/4)*4);
    const span=max-min||1,y=value=>bottom-(value-min)/span*plotHeight;
    const grid=Array.from({length:5},(_,index)=>{
      const value=min+span*index/4,level=y(value);
      return `<line x1="${left}" y1="${level}" x2="${right}" y2="${level}" class="widget-chart-grid"/><text x="${left-9}" y="${level+5}" text-anchor="end">${esc(c.formatField(value,axisField))}</text>`;
    }).join("");
    const step=plotWidth/categories.length,showLabels=categories.length*series.length<=12;
    const marks=series.map((item,index)=>{
      if(section.kind==="line"){
        const segments=[],dots=[];let points=[];
        (item.values||[]).forEach((value,category)=>{
          if(!hasValue(value)){if(points.length)segments.push(points);points=[];return;}
          const xx=left+step*(category+.5),yy=y(Number(value));points.push(`${xx},${yy}`);
          dots.push(`<circle cx="${xx}" cy="${yy}" r="4" fill="${color(index)}"${point(section,category,index)}><title>${esc(categories[category])} · ${esc(item.label)}: ${esc(c.detail(value,item,category))}</title></circle>${showLabels?`<text class="widget-value-label" x="${xx}" y="${yy-10}" text-anchor="middle"${point(section,category,index)}>${esc(c.format(value,item,category))}</text>`:""}`);
        });
        if(points.length)segments.push(points);
        return segments.map(segment=>`<polyline points="${segment.join(" ")}" fill="none" stroke="${color(index)}" stroke-width="4"/>`).join("")+dots.join("");
      }
      const barWidth=step*.78/series.length;
      return (item.values||[]).map((raw,category)=>{
        if(!hasValue(raw))return "";
        const value=Number(raw),yy=y(value),zero=y(0),xx=left+step*category+step*.11+index*barWidth;
        return `<rect x="${xx}" y="${Math.min(yy,zero)}" width="${barWidth}" height="${Math.abs(zero-yy)}" fill="${color(index)}"${point(section,category,index)}><title>${esc(categories[category])} · ${esc(item.label)}: ${esc(c.detail(raw,item,category))}</title></rect>${showLabels?`<text class="widget-value-label" x="${xx+barWidth/2}" y="${value<0?yy+18:yy-8}" text-anchor="middle"${point(section,category,index)}>${esc(c.format(raw,item,category))}</text>`:""}`;
      }).join("");
    }).join("");
    const labels=categories.map((label,index)=>`<text x="${left+step*(index+.5)}" y="${bottom+25}" text-anchor="middle"><title>${esc(label)}</title>${esc(String(label).length>18?String(label).slice(0,17)+"…":label)}</text>`).join("");
    const missing=series.flatMap(item=>(item.values||[]).map((value,index)=>hasValue(value)?null:`${categories[index]} · ${item.label}: ${item.reasons?.[index]||"Unavailable"}`)).filter(Boolean);
    return `<div class="widget-chart"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(section.name||"Chart")}">${grid}${marks}${labels}</svg>${legend(series.map(item=>item.label))}${missing.length?`<div class="widget-chart-warning">${esc(missing.join("; "))}</div>`:""}</div>`;
  }
  function render(section){
    if(section.chart?.panels?.length)return `<div class="widget-chart-panels">${section.chart.panels.map((panel,index)=>`<section class="widget-chart-panel" data-chart-panel-index="${index}"><h4>${esc(panel.label)}</h4>${render({...section,name:panel.label,kind:panel.kind||section.kind,chart:panel.chart})}</section>`).join("")}</div>`;
    const c=contract(section);
    if(!c.data.series?.length||!c.data.categories?.length)return empty("No chart data");
    const plot=section.kind==="pie"?(c.data.pie_mode==="percentage"?percentage(section,c):composition(section,c)):cartesian(section,c);
    return context(c)+(c.data.notice?`<div class="widget-chart-warning">${esc(c.data.notice)}</div>`:"")+plot;
  }
  function inspect(payload,target){
    const mark=target?.closest?.("[data-chart-point]");if(!mark)return null;
    const path=[];let element=mark.parentElement;
    while(element&&!element.matches?.("[data-widget-renderer]")){if(element.dataset?.chartPanelIndex!==undefined)path.unshift(Number(element.dataset.chartPanelIndex));element=element.parentElement;}
    let chart=payload.chart;for(const index of path)chart=chart?.panels?.[index]?.chart;
    const index=Number(mark.dataset.chartPoint),series=chart?.series?.[Number(mark.dataset.chartSeries)],detail=chart?.point_details?.[index];
    if(!series||!Number.isInteger(index))return null;
    const source=detail?.rows||payload.rows||[],indices=series.row_indices?.[index],rows=indices?indices.map(i=>source[i]).filter(Boolean):source;
    return {kind:"table",name:[detail?.label||chart.categories?.[index],series.aggregation_label||chart.aggregation_label].filter(Boolean).join(" · "),fields:detail?.fields||[...(payload.fields||[]),...(payload.calculation_fields||[])],rows,total_rows:rows.length};
  }
  window.StatsWidgetCharts=Object.freeze({render,inspect});
})();
