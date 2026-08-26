/* v117 on-Pi applied theme asset verification and temporary default isolation. */
(function(){
  const $=id=>document.getElementById(id);
  let timer=null;

  function esc(value){
    return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }

  function section(label){
    const stack=$("v98Sections");
    if(!stack) return null;
    const details=document.createElement("details");
    details.id="v117AssetProtection";
    details.className="v98-section";
    const summary=document.createElement("summary");
    summary.textContent=label;
    const body=document.createElement("div");
    body.className="v98-section-body";
    details.append(summary,body);
    return {stack,details,body};
  }

  function mount(){
    if($("v117AssetProtection")) return true;
    const made=section("Asset Protection");
    if(!made) return false;

    made.body.innerHTML=`
      <div class="small">Verify that every applied theme image is protected before removing anything from the default install.</div>
      <div id="v117AuditHeadline" style="font-weight:900;font-size:17px;margin-top:12px">Checking…</div>
      <div id="v117AuditCounts" class="small" style="margin-top:5px"></div>
      <div id="v117AuditIssues" class="small" style="margin-top:10px"></div>
      <div class="row" style="margin-top:12px">
        <button id="v117Verify" class="btn" type="button">Verify Now</button>
      </div>
      <div style="border-top:1px solid #2b2b2b;margin-top:15px;padding-top:14px">
        <label class="row" style="justify-content:space-between;gap:14px;align-items:center">
          <span>
            <strong>Test Without Default Assets</strong>
            <span class="small" style="display:block;margin-top:3px">Temporarily hides shipped theme/library images for 10 minutes. Nothing is deleted.</span>
          </span>
          <input id="v117DefaultToggle" type="checkbox" style="width:24px;height:24px;flex:0 0 auto">
        </label>
        <div id="v117TestStatus" class="small" style="margin-top:8px"></div>
      </div>`;

    const data=Array.from(made.stack.children).find(el=>
      String(el.querySelector(":scope > summary")?.textContent||"").trim()==="Data"
    );
    if(data) made.stack.insertBefore(made.details,data);
    else made.stack.appendChild(made.details);

    $("v117Verify").addEventListener("click",refresh);
    $("v117DefaultToggle").addEventListener("change",toggleTest);
    refresh();
    return true;
  }

  function formatTime(seconds){
    seconds=Math.max(0,Number(seconds||0));
    const minutes=Math.floor(seconds/60);
    const secs=Math.floor(seconds%60);
    return `${minutes}:${String(secs).padStart(2,"0")}`;
  }

  function paint(data){
    const audit=data?.audit||{};
    const test=data?.test||{};
    const headline=$("v117AuditHeadline");
    const counts=$("v117AuditCounts");
    const issues=$("v117AuditIssues");
    const toggle=$("v117DefaultToggle");
    const testStatus=$("v117TestStatus");
    if(!headline||!counts||!issues||!toggle||!testStatus) return;

    if(audit.safe){
      headline.textContent="✓ Storage audit passed";
      headline.style.color="#86d993";
    }else{
      headline.textContent=`✕ NOT SAFE — ${(audit.issues||[]).length} issue${(audit.issues||[]).length===1?"":"s"}`;
      headline.style.color="#ff9d9d";
    }

    counts.textContent=`${Number(audit.assets_protected||0)}/${Number(audit.assets_total||0)} applied assets protected · ${Number(audit.default_dependencies||0)} default dependencies · ${Number(audit.teams_checked||0)} teams checked`;

    const rows=(audit.issues||[]).slice(0,12);
    issues.innerHTML=rows.length
      ? rows.map(row=>`<div style="margin-top:4px">• ${esc(row.team)} — ${esc(row.asset)}: ${esc(row.problem)}</div>`).join("")
      : `<div>No applied theme depends on shipped default artwork.</div><div style="margin-top:3px">Permanent store: ${esc(audit.storage_path||"")}</div>`;

    toggle.checked=!!test.active;
    testStatus.textContent=test.active
      ? `Default assets are hidden now · ${formatTime(test.seconds_left)} remaining · cycle through every team on the TV. They restore automatically.`
      : "Default assets are available normally.";

    clearTimeout(timer);
    if(test.active) timer=setTimeout(refresh,5000);
  }

  async function refresh(){
    const button=$("v117Verify");
    if(button) button.disabled=true;
    try{
      const response=await fetch("/api/theme-asset-protection",{cache:"no-store"});
      const data=await response.json().catch(()=>({}));
      if(!response.ok||data.ok===false) throw new Error(data.error||"Could not verify assets.");
      paint(data);
    }catch(e){
      const headline=$("v117AuditHeadline");
      if(headline){
        headline.textContent=e.message||"Could not verify assets.";
        headline.style.color="#ff9d9d";
      }
    }finally{
      if(button) button.disabled=false;
    }
  }

  async function toggleTest(){
    const toggle=$("v117DefaultToggle");
    const status=$("v117TestStatus");
    if(!toggle) return;
    const enabled=toggle.checked;
    toggle.disabled=true;
    if(status) status.textContent=enabled?"Hiding default assets…":"Restoring default assets…";
    try{
      const response=await fetch("/api/theme-defaults-test",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({enabled})
      });
      const data=await response.json().catch(()=>({}));
      if(!response.ok||data.ok===false) throw new Error(data.error||"Could not change test mode.");
      paint(data);
    }catch(e){
      toggle.checked=!enabled;
      if(status) status.textContent=e.message||"Could not change test mode.";
    }finally{
      toggle.disabled=false;
    }
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(mount()) return;
      if(++tries<160) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();
