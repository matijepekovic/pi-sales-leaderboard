/* v124 Windows Tableau Login layout.
   Move the existing connection inputs out of Tableau Report > Advanced and
   into the existing Tableau Login dialog. The same DOM inputs and config APIs
   are reused so report discovery/mapping logic keeps one source of truth. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform))return;

  let mounted=false;
  let wrapped=false;

  function addStyles(){
    if(document.getElementById("windowsTableauLoginV124Styles"))return;
    const style=document.createElement("style");
    style.id="windowsTableauLoginV124Styles";
    style.textContent=`
      #dataSourceOverlay .tableau-login-note{margin:8px 0 18px;color:var(--muted);font-size:13px;line-height:1.45}
      #dataSourceOverlay .tableau-login-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:18px}
      #dataSourceOverlay .tableau-login-grid .tableau-login-wide{grid-column:1/-1}
      #dataSourceOverlay .tableau-login-secret{margin-top:14px}
      #dataSourceOverlay .tableau-login-actions{display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap;margin-top:16px}
      #dataSourceOverlay #testDataSource{min-width:132px}
      @media(max-width:720px){#dataSourceOverlay .tableau-login-grid{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function connectionValues(){
    return {
      server:String(document.getElementById("v90Server")?.value||"").trim(),
      site:String(document.getElementById("v90Site")?.value||"").trim(),
      pat_name:String(document.getElementById("v90PatName")?.value||"").trim(),
    };
  }

  function mount(){
    if(mounted)return true;
    const overlay=document.getElementById("dataSourceOverlay");
    const panel=overlay?.querySelector(".panel");
    const server=document.getElementById("v90Server");
    const site=document.getElementById("v90Site");
    const patName=document.getElementById("v90PatName");
    const secret=document.getElementById("tabPatSecret");
    const save=document.getElementById("saveDataSource");
    if(!panel||!server||!site||!patName||!secret||!save)return false;

    addStyles();
    mounted=true;

    const oldGrid=server.closest(".grid");
    const oldHeading=oldGrid?.previousElementSibling?.tagName==="H3"?oldGrid.previousElementSibling:null;

    const header=panel.querySelector(":scope > .row");
    const note=document.createElement("div");
    note.className="tableau-login-note";
    note.textContent="These credentials control the Tableau connection. Report, mapping, filters and dates are configured separately in Tableau Report.";
    header?.insertAdjacentElement("afterend",note);

    const grid=document.createElement("div");
    grid.id="tableauLoginConnectionV124";
    grid.className="tableau-login-grid";
    [server,site,patName].forEach(input=>{
      const field=input.parentElement;
      if(field)grid.appendChild(field);
    });
    note.insertAdjacentElement("afterend",grid);

    const secretHeading=secret.previousElementSibling;
    if(secretHeading?.tagName==="H3"){
      secretHeading.textContent="PAT secret";
      secretHeading.classList.add("tableau-login-secret");
    }

    if(oldGrid&&oldGrid.children.length===0)oldGrid.remove();
    if(oldHeading)oldHeading.remove();

    const originalActions=save.parentElement;
    originalActions?.classList.add("tableau-login-actions");
    if(originalActions)originalActions.style.justifyContent="flex-end";

    const test=document.createElement("button");
    test.id="testDataSource";
    test.className="btn";
    test.type="button";
    test.textContent="Test Connection";
    test.addEventListener("click",testConnection);
    originalActions?.insertBefore(test,save);

    wrapExistingLoginFunctions();
    applyDataSourceForm();
    return true;
  }

  function wrapExistingLoginFunctions(){
    if(wrapped)return;
    wrapped=true;

    const previousApply=applyDataSourceForm;
    applyDataSourceForm=function(){
      previousApply();
      const source=(config&&config.source&&typeof config.source==="object")?config.source:{};
      const server=document.getElementById("v90Server");
      const site=document.getElementById("v90Site");
      const patName=document.getElementById("v90PatName");
      if(server&&source.server!==undefined)server.value=source.server||"";
      if(site&&source.site!==undefined)site.value=source.site||"";
      if(patName&&source.pat_name!==undefined)patName.value=source.pat_name||"";
    };

    collectDataSource=function(){
      const values=connectionValues();
      const current=(config&&config.source&&typeof config.source==="object")?config.source:{};
      const payload={source:{...current,...values}};
      const secret=String(document.getElementById("tabPatSecret")?.value||"").trim();
      if(secret)payload.tableau_pat_secret=secret;
      return payload;
    };

    const previousSave=saveDataSource;
    saveDataSource=async function(closeAfter=false){
      const ok=await previousSave(false);
      if(!ok)return false;
      try{window.config=config;}catch(_){ }
      window.dispatchEvent(new CustomEvent("stats-tableau-login-saved",{detail:connectionValues()}));
      const status=document.getElementById("dataSourceStatus");
      if(status)status.textContent=closeAfter?"Login saved. Refreshing Tableau Report…":"Login saved.";
      if(closeAfter)setTimeout(()=>location.reload(),450);
      return true;
    };
  }

  async function testConnection(){
    const status=document.getElementById("dataSourceStatus");
    const test=document.getElementById("testDataSource");
    const save=document.getElementById("saveDataSource");
    const values=connectionValues();
    const pat_secret=String(document.getElementById("tabPatSecret")?.value||"").trim();
    if(!values.server||!values.site||!values.pat_name){
      if(status)status.textContent="Enter Server, Site and PAT Token Name first.";
      return;
    }
    if(status)status.textContent="Testing Tableau login…";
    if(test)test.disabled=true;
    if(save)save.disabled=true;
    try{
      const {r,d}=await request("/api/windows/tableau-login/test",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...values,pat_secret})
      });
      if(status){
        status.classList.toggle("ok",!!r.ok&&!!d.ok);
        status.textContent=(r.ok&&d.ok)?"Connection successful.":(d.error||"Connection failed.");
      }
    }catch(e){
      if(e.message!=="locked"&&status)status.textContent="Could not test the Tableau connection.";
    }finally{
      if(test)test.disabled=false;
      if(save)save.disabled=false;
    }
  }

  function boot(){
    if(mount())return;
    const observer=new MutationObserver(()=>{if(mount())observer.disconnect();});
    observer.observe(document.documentElement,{childList:true,subtree:true});
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();
})();
