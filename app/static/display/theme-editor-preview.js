/* v122 visual Theme Builder preview.
   Only runs inside the Windows Theme Builder iframe. It feeds stable fake sales
   data through the real leaderboard renderer, then adds direct mouse editing
   over theme-owned artwork. Real reps and real TV data are never modified. */
(function(){
  const params=new URLSearchParams(location.search);
  if(params.get("themeEditor")!=="1") return;
  const match=/^team-(\d+)$/.exec(String(params.get("preview")||""));
  if(!match) return;

  const teamId=Number(match[1]);
  const sampleSeed=Number(params.get("sample")||1)||1;
  const nativeFetch=window.fetch.bind(window);
  const DEFAULT={x:0,y:0,scale_x:100,scale_y:100,rotation:0,opacity:100};
  const LABELS={
    background:"Background",hero:"Hero / Header Art",row:"Leaderboard Row",
    champion:"Champion Row",medallion:"Champion Medallion",corner_tl:"Top Left Corner",
    corner_tr:"Top Right Corner",corner_bl:"Bottom Left Corner",corner_br:"Bottom Right Corner",
    totals_mark:"Totals Mark"
  };
  let selectedKey="";
  let selectedTarget=null;
  let selection=null;
  let menu=null;
  let drag=null;

  document.documentElement.dataset.themeEditor="1";

  function rng(seed){
    let a=(seed>>>0)||1;
    return function(){
      a|=0;a=a+0x6D2B79F5|0;
      let t=Math.imul(a^a>>>15,1|a);
      t=t+Math.imul(t^t>>>7,61|t)^t;
      return ((t^t>>>14)>>>0)/4294967296;
    };
  }
  function sampleNames(random){
    const first=["Jordan","Alex","Taylor","Casey","Riley","Cameron","Morgan","Avery","Drew","Jamie","Parker","Reese"];
    const last=["Lee","Morgan","Reed","Brooks","Adams","Hayes","Bennett","Cole","Price","Stone","Foster","Grant"];
    const names=[];
    while(names.length<7){
      const name=`${first[Math.floor(random()*first.length)]} ${last[Math.floor(random()*last.length)]}`;
      if(!names.includes(name)) names.push(name);
    }
    return names;
  }
  function makeFake(base){
    const random=rng((teamId*7919)+(sampleSeed*104729));
    const names=sampleNames(random);
    const leaderName=names.pop();
    const teamName=String(base?.team_summary?.team||base?.selected_team||`Team ${teamId}`);
    const makeRow=(name,index)=>{
      const issued=Math.round(32+random()*48);
      const pitched=Math.max(1,Math.round(issued*(0.68+random()*.25)));
      const sold=Math.max(1,Math.round(pitched*(0.24+random()*.36)));
      const gross=Math.round((sold*(4100+random()*3700))*100)/100;
      const pending=Math.round(gross*(.04+random()*.18)*100)/100;
      const net=Math.round((gross-pending*(.45+random()*.35))*100)/100;
      return {
        rep_key:`theme-preview-${sampleSeed}-${index}`,
        rep_name:name,team:teamName,team_id:teamId,assigned_team_id:teamId,
        issued_leads:issued,pitched_leads:pitched,pitched_rate:pitched/issued*100,
        sold_leads:sold,close_rate:sold/issued*100,gross_split:gross,pending_split:pending,
        net_split:net,dpl:net/issued,sales_retention:gross?net/gross*100:0,
        avg_gross_sale:sold?gross/sold:0,avg_net_sale:sold?net/sold:0
      };
    };
    const rows=names.map(makeRow);
    const leader=makeRow(leaderName,99);
    rows.push(leader);
    rows.sort((a,b)=>b.net_split-a.net_split);
    const sum=key=>rows.reduce((total,row)=>total+Number(row[key]||0),0);
    const issued=sum("issued_leads"),pitched=sum("pitched_leads"),sold=sum("sold_leads");
    const gross=sum("gross_split"),pending=sum("pending_split"),net=sum("net_split");
    const originalSummary=base?.team_summary||{};
    const summary={
      ...originalSummary,team:teamName,team_id:teamId,rep_count:rows.length,
      logo_url:originalSummary.logo_url||null,
      leads:[{lead_name:leaderName,lead_role:"Sales Manager"}],
      issued_leads:issued,pitched_leads:pitched,sold_leads:sold,
      pitched_rate:issued?pitched/issued*100:0,close_rate:issued?sold/issued*100:0,
      gross_split:gross,pending_split:pending,net_split:net,dpl:issued?net/issued:0,
      sales_retention:gross?net/gross*100:0,avg_gross_sale:sold?gross/sold:0,
      avg_net_sale:sold?net/sold:0
    };
    const metrics=["rank","rep_name","issued_leads","pitched_leads","sold_leads","close_rate","net_split"];
    return {
      ...base,mode:"per_team",mode_label:"Per Team",selected_team:teamName,
      rows,team_summary:summary,teams:[],metrics,sort_metric:"net_split",rank_direction:"desc",
      metric_types:{...(base?.metric_types||{}),rank:"system",rep_name:"text",issued_leads:"number",
        pitched_leads:"number",sold_leads:"number",close_rate:"percent",net_split:"currency"},
      metric_labels:{...(base?.metric_labels||{}),rank:"Rank",rep_name:"Sales Rep",issued_leads:"Issued",
        pitched_leads:"Pitched",sold_leads:"Sold",close_rate:"Close Rate",net_split:"Net Split"},
      theme_editor_sample:true
    };
  }

  window.fetch=async function(input,init){
    const url=typeof input==="string"?input:input?.url||"";
    if(url.startsWith("/api/leaderboard")){
      const response=await nativeFetch(input,init);
      if(!response.ok) return response;
      try{
        const base=await response.clone().json();
        const fake=makeFake(base);
        return new Response(JSON.stringify(fake),{
          status:response.status,statusText:response.statusText,
          headers:{"Content-Type":"application/json","Cache-Control":"no-store"}
        });
      }catch(_){return response;}
    }
    return nativeFetch(input,init);
  };

  function injectStyles(){
    if(document.getElementById("themeEditorPreviewV122Styles")) return;
    const style=document.createElement("style");
    style.id="themeEditorPreviewV122Styles";
    style.textContent=`
      html[data-theme-editor="1"],html[data-theme-editor="1"] body{user-select:none}
      html[data-theme-editor="1"] [data-theme-edit-key]{pointer-events:auto!important}
      .te-placeholder{position:absolute;z-index:45;display:grid;place-items:center;
        border:2px dashed rgba(80,190,255,.78);background:rgba(15,35,50,.38);color:#bfeaff;
        font:700 13px Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase;
        text-align:center;pointer-events:auto!important;box-sizing:border-box}
      .te-placeholder.te-hero{left:50%;top:8px;transform:translateX(-50%);width:min(52vw,760px);height:150px}
      .te-placeholder.te-corner{width:92px;height:92px;font-size:10px}
      .te-placeholder.te-corner.tl{left:7px;top:7px}.te-placeholder.te-corner.tr{right:7px;top:7px}
      .te-placeholder.te-corner.bl{left:7px;bottom:7px}.te-placeholder.te-corner.br{right:7px;bottom:7px}
      .te-placeholder.te-medal,.te-placeholder.te-totalmark{position:relative;inset:auto;width:58px;height:46px;
        margin:auto;font-size:8px;border-width:1px;background:rgba(15,35,50,.28)}
      #teSelection{position:fixed;z-index:2147483639;box-sizing:border-box;border:1px solid #43bfff;
        box-shadow:0 0 0 1px rgba(0,0,0,.6);pointer-events:auto;cursor:move;display:none}
      #teSelection::before{content:attr(data-label);position:absolute;left:0;bottom:calc(100% + 8px);
        padding:4px 7px;background:#07131c;color:#bfeaff;border:1px solid #43bfff;border-radius:4px;
        font:700 11px Arial,sans-serif;white-space:nowrap;pointer-events:none}
      .te-handle{position:absolute;width:12px;height:12px;background:#07131c;border:2px solid #43bfff;
        box-sizing:border-box;border-radius:2px;z-index:2}
      .te-handle.nw{left:-7px;top:-7px;cursor:nwse-resize}.te-handle.ne{right:-7px;top:-7px;cursor:nesw-resize}
      .te-handle.sw{left:-7px;bottom:-7px;cursor:nesw-resize}.te-handle.se{right:-7px;bottom:-7px;cursor:nwse-resize}
      .te-handle.n{left:50%;top:-7px;margin-left:-6px;cursor:ns-resize}.te-handle.s{left:50%;bottom:-7px;margin-left:-6px;cursor:ns-resize}
      .te-handle.w{left:-7px;top:50%;margin-top:-6px;cursor:ew-resize}.te-handle.e{right:-7px;top:50%;margin-top:-6px;cursor:ew-resize}
      .te-rotate-line{position:absolute;left:50%;bottom:100%;width:1px;height:28px;background:#43bfff;pointer-events:none}
      .te-rotate{position:absolute;left:50%;bottom:calc(100% + 23px);width:15px;height:15px;margin-left:-7px;
        border:2px solid #43bfff;border-radius:50%;background:#07131c;cursor:crosshair;z-index:3}
      #teContext{position:fixed;z-index:2147483640;min-width:215px;padding:7px;background:#111b23;color:#fff;
        border:1px solid #3a596d;border-radius:8px;box-shadow:0 14px 38px rgba(0,0,0,.5);font:13px Arial,sans-serif;display:none}
      #teContext button{width:100%;min-height:38px;padding:8px 10px;border:0;border-radius:5px;background:transparent;
        color:#fff;text-align:left;font:600 13px Arial,sans-serif;cursor:pointer}
      #teContext button:hover{background:#203546}
      #teContext .te-danger{color:#ffb4b4}
      #teContext .te-opacity{padding:8px 10px;border-top:1px solid #2e4657;border-bottom:1px solid #2e4657;margin:4px 0}
      #teContext .te-opacity-row{display:flex;justify-content:space-between;gap:10px;margin-bottom:5px;color:#c9d7e1}
      #teContext input[type=range]{width:100%;accent-color:#43bfff}
      #teEditorTip{position:fixed;left:16px;bottom:14px;z-index:2147483638;padding:7px 10px;border-radius:6px;
        background:rgba(6,14,20,.78);border:1px solid rgba(67,191,255,.35);color:#b9cad5;
        font:12px Arial,sans-serif;pointer-events:none}
    `;
    document.head.appendChild(style);
  }

  function post(action,key=selectedKey){
    try{
      if(window.parent!==window&&window.parent.StatsThemeEditorHost?.action){
        window.parent.StatsThemeEditorHost.action(action,key,teamId);
        return;
      }
    }catch(_){ }
    try{window.parent.postMessage({type:"stats-theme-editor",action,key,teamId},location.origin);}catch(_){ }
  }
  function currentCfg(key=selectedKey){
    return window.StatsThemeTransforms?.get?.(teamId,key)||{...DEFAULT};
  }
  function setLocal(key,value){
    window.StatsThemeTransforms?.setLocal?.(teamId,key,value);
    const target=(selectedKey===key&&selectedTarget)?selectedTarget:null;
    if(target?.classList.contains("te-placeholder")){
      const base=target.dataset.tePlaceholderBase||"";
      target.style.opacity=String(value.opacity/100);
      target.style.transform=`${base?base+" ":""}translate(${value.x}%,${value.y}%) scale(${value.scale_x/100},${value.scale_y/100}) rotate(${value.rotation}deg)`;
    }
  }
  async function persist(key,value){
    try{
      await nativeFetch(`/api/windows/theme-transforms/${teamId}`,{
        method:"PUT",headers:{"Content-Type":"application/json"},cache:"no-store",
        body:JSON.stringify({asset:key,transform:value})
      });
    }catch(_){ }
  }
  async function resetTransform(key){
    try{await nativeFetch(`/api/windows/theme-transforms/${teamId}/${encodeURIComponent(key)}`,{method:"DELETE",cache:"no-store"});}catch(_){ }
    setLocal(key,{...DEFAULT});
    if(selectedKey===key) updateSelection();
  }

  function ensureSelection(){
    if(selection) return selection;
    selection=document.createElement("div");
    selection.id="teSelection";
    selection.innerHTML=`
      <span class="te-handle nw" data-handle="nw"></span><span class="te-handle n" data-handle="n"></span>
      <span class="te-handle ne" data-handle="ne"></span><span class="te-handle e" data-handle="e"></span>
      <span class="te-handle se" data-handle="se"></span><span class="te-handle s" data-handle="s"></span>
      <span class="te-handle sw" data-handle="sw"></span><span class="te-handle w" data-handle="w"></span>
      <span class="te-rotate-line"></span><span class="te-rotate" data-handle="rotate" title="Rotate"></span>`;
    document.body.appendChild(selection);
    selection.addEventListener("pointerdown",startDrag);
    selection.addEventListener("contextmenu",e=>{e.preventDefault();showMenu(e.clientX,e.clientY,selectedKey,selectedTarget);});
    return selection;
  }
  function ensureMenu(){
    if(menu) return menu;
    menu=document.createElement("div");menu.id="teContext";
    menu.innerHTML=`
      <button type="button" data-action="upload">Upload New Asset…</button>
      <button type="button" data-action="color">Change Color…</button>
      <div class="te-opacity"><div class="te-opacity-row"><span>Opacity</span><strong id="teOpacityValue">100%</strong></div>
        <input id="teOpacity" type="range" min="0" max="100" step="1" value="100"></div>
      <button type="button" data-action="reset-transform">Reset Position / Size</button>
      <button type="button" class="te-danger" data-action="remove">Remove Asset</button>`;
    document.body.appendChild(menu);
    menu.addEventListener("click",e=>{
      const button=e.target.closest("button[data-action]");if(!button)return;
      const action=button.dataset.action;
      if(action==="upload")post("upload");
      if(action==="color")post("color");
      if(action==="remove")post("remove");
      if(action==="reset-transform")resetTransform(selectedKey);
      hideMenu();
    });
    const opacity=menu.querySelector("#teOpacity");
    opacity.addEventListener("input",()=>{
      if(!selectedKey)return;
      const value={...currentCfg(),opacity:Number(opacity.value)};
      menu.querySelector("#teOpacityValue").textContent=`${Math.round(value.opacity)}%`;
      setLocal(selectedKey,value);updateSelection();
    });
    opacity.addEventListener("change",()=>{if(selectedKey)persist(selectedKey,currentCfg());});
    return menu;
  }
  function hideMenu(){if(menu)menu.style.display="none";}
  function showMenu(x,y,key,target){
    if(!key)return;
    select(key,target);
    const m=ensureMenu(),c=currentCfg(key);
    m.querySelector("#teOpacity").value=String(Math.round(c.opacity));
    m.querySelector("#teOpacityValue").textContent=`${Math.round(c.opacity)}%`;
    m.style.display="block";
    const w=m.offsetWidth,h=m.offsetHeight;
    m.style.left=`${Math.max(8,Math.min(innerWidth-w-8,x))}px`;
    m.style.top=`${Math.max(8,Math.min(innerHeight-h-8,y))}px`;
  }

  function findTarget(key){
    const all=[...document.querySelectorAll(`[data-theme-edit-key="${CSS.escape(key)}"]`)];
    if(!all.length)return null;
    if(key==="row")return all.find(el=>el.classList.contains("bt-row")&&!el.classList.contains("champion"))||all[0];
    return all[0];
  }
  function select(key,target){
    selectedKey=key||"";
    selectedTarget=target||findTarget(selectedKey);
    const box=ensureSelection();
    if(!selectedKey||!selectedTarget){box.style.display="none";return;}
    box.dataset.label=LABELS[selectedKey]||selectedKey;
    box.style.display="block";
    updateSelection();
    post("selected");
  }
  function updateSelection(){
    if(!selection||!selectedTarget||!selectedTarget.isConnected){
      if(selectedKey){selectedTarget=findTarget(selectedKey);}
      if(!selectedTarget){if(selection)selection.style.display="none";return;}
    }
    const rect=selectedTarget.getBoundingClientRect();
    if(rect.width<2||rect.height<2){selection.style.display="none";return;}
    selection.style.display="block";
    selection.style.left=`${rect.left}px`;selection.style.top=`${rect.top}px`;
    selection.style.width=`${rect.width}px`;selection.style.height=`${rect.height}px`;
  }

  function startDrag(e){
    if(!selectedKey||!selectedTarget)return;
    e.preventDefault();hideMenu();
    const handle=e.target.dataset.handle||"move";
    const rect=selectedTarget.getBoundingClientRect();
    const cfg={...currentCfg()};
    drag={pointerId:e.pointerId,handle,startX:e.clientX,startY:e.clientY,rect,cfg,
      centerX:rect.left+rect.width/2,centerY:rect.top+rect.height/2};
    try{selection.setPointerCapture(e.pointerId);}catch(_){ }
  }
  function moveDrag(e){
    if(!drag||e.pointerId!==drag.pointerId)return;
    e.preventDefault();
    const dx=e.clientX-drag.startX,dy=e.clientY-drag.startY;
    const c={...drag.cfg};
    const w=Math.max(24,drag.rect.width),h=Math.max(24,drag.rect.height);
    if(drag.handle==="move"){
      c.x=drag.cfg.x+dx/w*100;c.y=drag.cfg.y+dy/h*100;
    }else if(drag.handle==="rotate"){
      const a0=Math.atan2(drag.startY-drag.centerY,drag.startX-drag.centerX);
      const a1=Math.atan2(e.clientY-drag.centerY,e.clientX-drag.centerX);
      c.rotation=drag.cfg.rotation+(a1-a0)*180/Math.PI;
      while(c.rotation>180)c.rotation-=360;while(c.rotation<-180)c.rotation+=360;
    }else{
      const hasE=drag.handle.includes("e"),hasW=drag.handle.includes("w");
      const hasS=drag.handle.includes("s"),hasN=drag.handle.includes("n");
      if(hasE||hasW){
        const sign=hasE?1:-1;
        const factor=Math.max(.2,1+(dx*sign)/w);
        c.scale_x=Math.max(20,Math.min(500,drag.cfg.scale_x*factor));
        c.x=drag.cfg.x+dx/(2*w)*100;
      }
      if(hasS||hasN){
        const sign=hasS?1:-1;
        const factor=Math.max(.2,1+(dy*sign)/h);
        c.scale_y=Math.max(20,Math.min(500,drag.cfg.scale_y*factor));
        c.y=drag.cfg.y+dy/(2*h)*100;
      }
      if(e.shiftKey&&(hasE||hasW)&&(hasS||hasN)){
        const scale=Math.max(c.scale_x,c.scale_y);
        c.scale_x=scale;c.scale_y=scale;
      }
    }
    c.x=Math.max(-300,Math.min(300,c.x));c.y=Math.max(-300,Math.min(300,c.y));
    c.rotation=Math.max(-180,Math.min(180,c.rotation));
    setLocal(selectedKey,c);
    requestAnimationFrame(updateSelection);
  }
  function endDrag(e){
    if(!drag||e.pointerId!==drag.pointerId)return;
    const key=selectedKey,value={...currentCfg()};
    drag=null;
    try{selection.releasePointerCapture(e.pointerId);}catch(_){ }
    persist(key,value);updateSelection();
  }

  function editableFromEvent(e){
    const direct=e.target.closest?.("[data-theme-edit-key]");
    if(direct)return direct;
    const root=document.getElementById("themedTeamBroadcast");
    if(root&&root.contains(e.target))return root.querySelector(".bt-bg");
    return null;
  }
  function bindEvents(){
    document.addEventListener("dblclick",e=>{
      const target=editableFromEvent(e);if(!target)return;
      e.preventDefault();e.stopPropagation();select(target.dataset.themeEditKey||"background",target);
    },true);
    document.addEventListener("contextmenu",e=>{
      const target=editableFromEvent(e);if(!target)return;
      e.preventDefault();e.stopPropagation();showMenu(e.clientX,e.clientY,target.dataset.themeEditKey||"background",target);
    },true);
    document.addEventListener("pointerdown",e=>{
      if(menu&&menu.style.display==="block"&&!menu.contains(e.target))hideMenu();
      if(selection&&selection.style.display==="block"&&!selection.contains(e.target)&&!e.target.closest?.("[data-theme-edit-key]")){
        selectedKey="";selectedTarget=null;selection.style.display="none";
      }
    },true);
    document.addEventListener("pointermove",moveDrag,true);
    document.addEventListener("pointerup",endDrag,true);
    document.addEventListener("pointercancel",endDrag,true);
    document.addEventListener("keydown",e=>{
      if(e.key==="Escape"){hideMenu();selectedKey="";selectedTarget=null;if(selection)selection.style.display="none";}
    });
    window.addEventListener("resize",()=>requestAnimationFrame(updateSelection));
  }

  function placeholder(parent,key,className,text){
    if(parent.querySelector(`.te-placeholder[data-theme-edit-key="${key}"]`))return;
    const el=document.createElement("div");el.className=`te-placeholder ${className}`;
    el.dataset.themeEditKey=key;el.textContent=text||LABELS[key]||key;
    if(className.includes("te-hero"))el.dataset.tePlaceholderBase="translateX(-50%)";
    parent.appendChild(el);
    setLocal(key,currentCfg(key));
  }
  function decorate(){
    injectStyles();
    const root=document.getElementById("themedTeamBroadcast");if(!root)return;
    const bg=root.querySelector(".bt-bg");if(bg)bg.dataset.themeEditKey="background";
    const hero=root.querySelector(".bt-hero");
    if(hero)hero.dataset.themeEditKey="hero";else placeholder(root.querySelector(".bt-header")||root,"hero","te-hero","Hero / Logo");

    const corners={corner_tl:"tl",corner_tr:"tr",corner_bl:"bl",corner_br:"br"};
    Object.entries(corners).forEach(([key,pos])=>{
      const el=root.querySelector(`.bt-corner.${pos}`);
      if(el)el.dataset.themeEditKey=key;else placeholder(root,key,`te-corner ${pos}`,LABELS[key]);
    });

    root.querySelectorAll(".bt-row").forEach(row=>{
      if(row.classList.contains("team-lead"))return;
      row.dataset.themeEditKey=row.classList.contains("champion")?"champion":"row";
    });
    const champion=root.querySelector(".bt-row.champion");
    if(champion){
      const medal=champion.querySelector(".bt-medal");
      if(medal)medal.dataset.themeEditKey="medallion";
      else placeholder(champion.querySelector(".bt-rank")||champion,"medallion","te-medal","Medal");
    }
    const lead=root.querySelector(".bt-row.team-lead");
    if(lead){
      const mark=lead.querySelector(".bt-tl-mark");
      if(mark)mark.dataset.themeEditKey="totals_mark";
      else placeholder(lead.querySelector(".bt-rank")||lead,"totals_mark","te-totalmark","Totals Mark");
    }

    if(!document.getElementById("teEditorTip")){
      const tip=document.createElement("div");tip.id="teEditorTip";
      tip.textContent="Double-click artwork to resize / rotate • Right-click to change it";
      document.body.appendChild(tip);
    }
    if(selectedKey){selectedTarget=findTarget(selectedKey);requestAnimationFrame(updateSelection);}
    post("ready","");
  }

  injectStyles();bindEvents();ensureSelection();ensureMenu();
  Display.stage(180, function(data, next){
    const result=next(data);
    decorate();requestAnimationFrame(decorate);setTimeout(decorate,80);
    return result;
  });
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",()=>setTimeout(decorate,0),{once:true});
  else setTimeout(decorate,0);
})();
