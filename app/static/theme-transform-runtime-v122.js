/* v122 Windows visual-theme transform runtime.
   Theme Studio still owns artwork, colors, corner seating and hero scale. This
   layer only adds the direct-canvas transform values saved by the Windows
   editor: move, resize, rotate and opacity. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform) || typeof render!=="function") return;

  const DEFAULT={x:0,y:0,scale_x:100,scale_y:100,rotation:0,opacity:100};
  let teams={};
  let loaded=false;
  let loading=null;
  let currentData=null;
  let lastSettingsVersion=null;

  const clamp=(v,a,b,d)=>{v=Number(v);return Number.isFinite(v)?Math.min(b,Math.max(a,v)):d;};
  function clean(raw){
    raw=raw&&typeof raw==="object"?raw:{};
    return {
      x:clamp(raw.x,-300,300,0),y:clamp(raw.y,-300,300,0),
      scale_x:clamp(raw.scale_x,20,500,100),scale_y:clamp(raw.scale_y,20,500,100),
      rotation:clamp(raw.rotation,-180,180,0),opacity:clamp(raw.opacity,0,100,100)
    };
  }
  function teamId(data){
    return Number(data?.team_summary?.team_id||0)||null;
  }
  function cfg(team,key){
    return clean(teams?.[String(team)]?.[key]||DEFAULT);
  }
  function transformText(c){
    return `translate(${c.x}%,${c.y}%) scale(${c.scale_x/100},${c.scale_y/100}) rotate(${c.rotation}deg)`;
  }

  function ensureStyles(){
    if(document.getElementById("themeTransformRuntimeV122Styles")) return;
    const style=document.createElement("style");
    style.id="themeTransformRuntimeV122Styles";
    style.textContent=`
      #themedTeamBroadcast .bt-row.te-transform-row{background-image:none!important}
      #themedTeamBroadcast .bt-row.te-transform-row::after{
        content:"";position:absolute;inset:0;z-index:0;pointer-events:none;
        background-image:var(--te-row-image,none);background-position:center;
        background-size:100% 100%;background-repeat:no-repeat;
        transform-origin:center center;transform:var(--te-row-transform,none);
        opacity:var(--te-row-opacity,1);will-change:transform,opacity
      }
      #themedTeamBroadcast .bt-row.te-transform-row::before{z-index:1}
      #themedTeamBroadcast .bt-row.te-transform-row>*{z-index:2}
    `;
    document.head.appendChild(style);
  }

  function applyElement(el,c,key){
    if(!el) return;
    if(el.dataset.teBaseTransform===undefined){
      el.dataset.teBaseTransform=String(el.style.transform||"");
      el.dataset.teBaseOpacity=String(el.style.opacity||"");
    }
    const base=String(el.dataset.teBaseTransform||"").trim();
    el.style.transformOrigin=el.style.transformOrigin||"center center";
    el.style.transform=`${base?base+" ":""}${transformText(c)}`;
    el.style.opacity=String(c.opacity/100);
    el.style.willChange="transform,opacity";
    el.dataset.themeEditKey=key;
  }

  function rowImage(row){
    const inline=String(row.style.backgroundImage||"").trim();
    if(inline&&inline!=="none") return inline;
    const saved=String(row.style.getPropertyValue("--te-row-image")||"").trim();
    return saved||"none";
  }
  function applyRow(row,c,key){
    if(!row) return;
    const image=rowImage(row);
    if(image&&image!=="none") row.style.setProperty("--te-row-image",image);
    row.style.backgroundImage="none";
    row.style.setProperty("--te-row-transform",transformText(c));
    row.style.setProperty("--te-row-opacity",String(c.opacity/100));
    row.classList.add("te-transform-row");
    row.dataset.themeEditKey=key;
  }

  function apply(data){
    ensureStyles();
    const tid=teamId(data);
    const root=document.getElementById("themedTeamBroadcast");
    if(!tid||!root) return;

    applyElement(root.querySelector(".bt-bg"),cfg(tid,"background"),"background");
    const hero=root.querySelector(".bt-hero");
    if(hero) applyElement(hero,cfg(tid,"hero"),"hero");

    const corners={corner_tl:"tl",corner_tr:"tr",corner_bl:"bl",corner_br:"br"};
    Object.entries(corners).forEach(([key,pos])=>{
      applyElement(root.querySelector(`.bt-corner.${pos}`),cfg(tid,key),key);
    });

    root.querySelectorAll(".bt-row").forEach(row=>{
      const key=row.classList.contains("champion")?"champion":"row";
      if(!row.classList.contains("team-lead")) applyRow(row,cfg(tid,key),key);
    });
    root.querySelectorAll(".bt-medal").forEach(el=>applyElement(el,cfg(tid,"medallion"),"medallion"));
    root.querySelectorAll(".bt-tl-mark").forEach(el=>applyElement(el,cfg(tid,"totals_mark"),"totals_mark"));
  }

  async function reload(force=false){
    if(loading&&!force) return loading;
    loading=(async()=>{
      try{
        const r=await fetch("/api/windows/theme-transforms",{cache:"no-store"});
        if(!r.ok) return false;
        const d=await r.json();
        if(d&&d.ok!==false){teams=d.teams||{};loaded=true;return true;}
      }catch(_){ }
      return false;
    })();
    try{return await loading;}finally{loading=null;}
  }

  function setLocal(tid,key,value){
    const id=String(Number(tid)||0);
    if(!id||id==="0") return;
    if(!teams[id]) teams[id]={};
    teams[id][key]=clean(value);
    if(currentData&&teamId(currentData)===Number(tid)) apply(currentData);
  }
  function getLocal(tid,key){return cfg(Number(tid)||0,key);}

  const previousRender=render;
  render=function(data){
    const result=previousRender(data);
    currentData=data;
    apply(data);
    const version=Number(data?.settings_version||0);
    if(!loaded||version!==lastSettingsVersion){
      lastSettingsVersion=version;
      reload().then(()=>{if(currentData)apply(currentData);});
    }
    requestAnimationFrame(()=>{if(currentData===data)apply(data);});
    return result;
  };

  window.StatsThemeTransforms={get:getLocal,setLocal,apply:()=>currentData&&apply(currentData),reload};
  reload().then(()=>{if(currentData)apply(currentData);});
})();
