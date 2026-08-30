/* v127 Theme Builder discoverability hotfix.
   The previous observer rewrote menu text on every DOM mutation. Setting
   textContent itself creates a child mutation, so Chromium could get trapped
   in a self-triggering observer loop and mark the entire Settings page
   unresponsive. All decoration below is idempotent and observer work is
   coalesced to one animation frame. */
(function(){
  const params=new URLSearchParams(location.search);
  if(params.get("themeEditor")!=="1") return;

  const LABELS={
    background:"Background",hero:"Hero / Header Art",row:"Leaderboard Row",
    champion:"Champion Row",medallion:"Champion Medallion",corner_tl:"Top Left Corner",
    corner_tr:"Top Right Corner",corner_bl:"Bottom Left Corner",corner_br:"Bottom Right Corner",
    totals_mark:"Totals Mark"
  };
  const COACH_KEY="stats.themeEditor.coach.v123.dismissed";
  let decorateQueued=false;

  function injectStyles(){
    if(document.getElementById("themeEditorIntuitiveV123Styles"))return;
    const style=document.createElement("style");
    style.id="themeEditorIntuitiveV123Styles";
    style.textContent=`
      html[data-theme-editor="1"] [data-theme-edit-key]:not(.bt-bg):hover{
        outline:1px dashed rgba(102,205,255,.9);outline-offset:-2px;cursor:pointer
      }
      html[data-theme-editor="1"] .bt-bg[data-theme-edit-key]{cursor:pointer}
      html[data-theme-editor="1"] .te-placeholder{
        transition:border-color .12s ease,background .12s ease,box-shadow .12s ease
      }
      html[data-theme-editor="1"] .te-placeholder:hover{
        border-color:#8bd8ff;background:rgba(25,57,76,.55);box-shadow:0 0 0 2px rgba(67,191,255,.12)
      }
      html[data-theme-editor="1"] .te-placeholder .te-empty-label{display:block;font-size:10px;line-height:1.15}
      html[data-theme-editor="1"] .te-placeholder .te-empty-action{
        display:block;margin-top:4px;font-size:9px;line-height:1.1;color:#fff;letter-spacing:.02em;text-transform:none
      }
      #teSelection::before{font-size:12px!important;font-weight:800!important}
      #teSelection .te-rotate{width:20px!important;height:20px!important;margin-left:-10px!important;
        bottom:calc(100% + 21px)!important;border-radius:50%!important;background:#10222e!important;
        display:grid!important;place-items:center!important;cursor:grab!important}
      #teSelection .te-rotate:active{cursor:grabbing!important}
      #teSelection .te-rotate::after{content:"↻";color:#d9f3ff;font:700 13px/1 Arial,sans-serif;pointer-events:none}
      #teSelection .te-rotate-line{height:27px!important}
      #teCoachV123{position:fixed;inset:0;z-index:2147483646;display:grid;place-items:center;
        padding:24px;background:rgba(0,0,0,.46);font-family:Arial,sans-serif}
      #teCoachV123 .te-coach-card{width:min(430px,calc(100vw - 40px));padding:20px 22px;border-radius:12px;
        background:#101820;color:#fff;border:1px solid #416a80;box-shadow:0 22px 70px rgba(0,0,0,.55)}
      #teCoachV123 h2{margin:0 0 8px;font-size:20px}
      #teCoachV123 p{margin:0;color:#c7d5de;font-size:14px;line-height:1.5}
      #teCoachV123 .te-coach-main{margin-top:13px;padding:12px;border-radius:8px;background:#172630;
        color:#e9f7ff;font-weight:700;line-height:1.55}
      #teCoachV123 button{margin-top:16px;min-width:96px;min-height:40px;border:1px solid #62c9ff;
        border-radius:7px;background:#16384b;color:#fff;font-weight:800;cursor:pointer}
    `;
    document.head.appendChild(style);
  }

  function setTextIfChanged(el,text){
    if(el&&el.textContent!==text)el.textContent=text;
  }

  function simplifyMenu(){
    const menu=document.getElementById("teContext");if(!menu)return;
    const names={upload:"Replace Image…",color:"Color…","reset-transform":"Reset",remove:"Remove"};
    Object.entries(names).forEach(([action,label])=>{
      setTextIfChanged(menu.querySelector(`button[data-action="${action}"]`),label);
    });
    setTextIfChanged(menu.querySelector(".te-opacity-row span"),"Opacity");
  }

  function decorateEditable(){
    document.querySelectorAll("[data-theme-edit-key]").forEach(el=>{
      const key=String(el.dataset.themeEditKey||"");
      const label=LABELS[key]||key;
      const title=label?`Double-click to edit ${label}`:"";
      if(title&&!el.title)el.title=title;
    });

    document.querySelectorAll(".te-placeholder[data-theme-edit-key]").forEach(el=>{
      const key=String(el.dataset.themeEditKey||"");
      const label=LABELS[key]||key;
      if(el.dataset.v123Empty!=="1"){
        el.dataset.v123Empty="1";
        el.innerHTML=`<span class="te-empty-label">${label}</span><span class="te-empty-action">Double-click to add</span>`;
      }
      const title=`Double-click to add ${label}`;
      if(el.title!==title)el.title=title;
    });
    simplifyMenu();
  }

  function scheduleDecorate(){
    if(decorateQueued)return;
    decorateQueued=true;
    requestAnimationFrame(()=>{
      decorateQueued=false;
      decorateEditable();
    });
  }

  function showCoach(force=false){
    if(document.getElementById("teCoachV123"))return;
    if(!force){
      try{if(localStorage.getItem(COACH_KEY)==="1")return;}catch(_){ }
    }
    const overlay=document.createElement("div");overlay.id="teCoachV123";
    overlay.innerHTML=`<div class="te-coach-card" role="dialog" aria-modal="true" aria-label="Theme Builder mouse controls">
      <h2>Edit the preview directly</h2>
      <p>Move your mouse over artwork to see what can be edited.</p>
      <div class="te-coach-main">Double-click artwork to edit<br>Right-click artwork for options<br>Drag the box to move • handles resize • ↻ rotates</div>
      <button type="button">Got it</button>
    </div>`;
    document.body.appendChild(overlay);
    const dismiss=()=>{
      try{localStorage.setItem(COACH_KEY,"1");}catch(_){ }
      overlay.remove();
    };
    overlay.querySelector("button").addEventListener("click",dismiss);
    overlay.addEventListener("pointerdown",e=>{if(e.target===overlay)dismiss();});
  }

  window.addEventListener("message",event=>{
    if(event.origin!==location.origin||event.data?.type!=="stats-theme-editor-help")return;
    showCoach(true);
  });

  function boot(){
    injectStyles();
    decorateEditable();
    const observer=new MutationObserver(scheduleDecorate);
    observer.observe(document.documentElement,{
      childList:true,subtree:true,attributes:true,attributeFilter:["data-theme-edit-key"]
    });
    setTimeout(()=>showCoach(false),450);
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();
})();
