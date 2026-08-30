/* v126 Theme Builder preview data policy.

   The visual editor still uses the real leaderboard renderer. This layer fixes
   two product rules:
   - a team with real, locally assigned reps always previews its real names and
     real stats; fake sample rows are never allowed to replace populated data;
   - an empty team gets a clearly marked mock preview so Theme Builder still has
     rows and artwork targets to design against.

   Theme Builder previews are also intentionally static while the editor is
   open. The normal TV refresh loop is stopped after one corrected load; Theme
   Studio explicitly reloads the iframe when a theme change needs a refresh.
   This removes the repeated full-board rerender loop that could make Chromium
   report the Settings page as unresponsive on Windows laptops. */
(function(){
  const params=new URLSearchParams(location.search);
  if(params.get("themeEditor")!=="1") return;

  const previousFetch=window.fetch.bind(window);
  let mockMode=false;

  function urlOf(input){
    try{return new URL(typeof input==="string"?input:(input?.url||""),location.href);}
    catch(_){return null;}
  }

  function assignedRows(data){
    return (Array.isArray(data?.rows)?data.rows:[]).filter(row=>Number(row?.assigned_team_id||0)>0);
  }

  function responseFrom(data,status=200,statusText="OK"){
    return new Response(JSON.stringify(data),{
      status,statusText,
      headers:{"Content-Type":"application/json","Cache-Control":"no-store"}
    });
  }

  /* Use XHR for the real-data probe so it bypasses the older visual-editor
     fetch wrapper, which deliberately manufactures sample rows. */
  function readRealLeaderboard(url){
    return new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();
      xhr.open("GET",`${url.pathname}${url.search}`,true);
      xhr.setRequestHeader("Cache-Control","no-store");
      xhr.onload=()=>{
        try{
          if(xhr.status<200||xhr.status>=300)throw new Error("leaderboard probe failed");
          resolve({data:JSON.parse(xhr.responseText||"{}"),status:xhr.status,statusText:xhr.statusText||"OK"});
        }catch(error){reject(error);}
      };
      xhr.onerror=()=>reject(new Error("leaderboard probe failed"));
      xhr.send();
    });
  }

  function setMockMode(on){
    mockMode=!!on;
    if(mockMode)document.documentElement.dataset.themeEditorMock="1";
    else delete document.documentElement.dataset.themeEditorMock;
  }

  window.fetch=async function(input,init){
    const url=urlOf(input);
    if(url&&url.origin===location.origin&&url.pathname==="/api/leaderboard"){
      try{
        const real=await readRealLeaderboard(url);
        if(assignedRows(real.data).length){
          setMockMode(false);
          return responseFrom(real.data,real.status,real.statusText);
        }
        // No locally assigned reps: let the existing v122 editor create its
        // stable fake rows so the canvas remains useful for a brand-new team.
        setMockMode(true);
        return previousFetch(input,init);
      }catch(_){
        return previousFetch(input,init);
      }
    }
    return previousFetch(input,init);
  };

  function injectStyles(){
    if(document.getElementById("themeEditorDataPolicyV126Styles"))return;
    const style=document.createElement("style");
    style.id="themeEditorDataPolicyV126Styles";
    style.textContent=`
      html[data-theme-editor="1"] *,html[data-theme-editor="1"] *::before,html[data-theme-editor="1"] *::after{
        animation-duration:0s!important;animation-delay:0s!important
      }
      html[data-theme-editor-mock="1"] #themedTeamBroadcast .bt-bg.te-mock-bg{
        background-image:
          radial-gradient(circle at 18% 18%,rgba(216,179,74,.20),transparent 34%),
          radial-gradient(circle at 82% 12%,rgba(216,179,74,.12),transparent 30%),
          linear-gradient(145deg,#070707 0%,#131313 54%,#080808 100%)!important
      }
      html[data-theme-editor-mock="1"] .te-placeholder{
        background:
          linear-gradient(135deg,rgba(216,179,74,.16),rgba(18,35,46,.58))!important;
        border-color:rgba(216,179,74,.78)!important;color:#f5df9a!important
      }
      #teMockBadgeV126{position:fixed;left:16px;top:14px;z-index:2147483638;
        padding:7px 10px;border:1px solid rgba(216,179,74,.58);border-radius:6px;
        background:rgba(12,10,5,.88);color:#f4dda0;font:700 11px Arial,sans-serif;
        letter-spacing:.04em;pointer-events:none}
    `;
    document.head.appendChild(style);
  }

  function decorateMockPreview(){
    injectStyles();
    const root=document.getElementById("themedTeamBroadcast");
    let badge=document.getElementById("teMockBadgeV126");
    if(!mockMode){
      if(badge)badge.remove();
      root?.querySelector(".bt-bg")?.classList.remove("te-mock-bg");
      return;
    }

    if(root){
      const bg=root.querySelector(".bt-bg");
      if(bg){
        const image=getComputedStyle(bg).backgroundImage;
        bg.classList.toggle("te-mock-bg",!image||image==="none");
      }
    }
    if(!badge){
      badge=document.createElement("div");badge.id="teMockBadgeV126";
      badge.textContent="MOCK PREVIEW · no assigned reps yet";
      document.body.appendChild(badge);
    }
  }

  if(typeof render==="function"){
    Display.stage(190, function(data, next){
      const result=next(data);
      requestAnimationFrame(decorateMockPreview);
      return result;
    });
  }

  /* The base display script has already scheduled one refresh timer by the time
     this file loads. Replace getRefresh so that timer performs one last load and
     then stops instead of scheduling forever inside the editor iframe. */
  if(typeof getRefresh==="function"&&typeof load==="function"){
    getRefresh=async function(){
      try{await load();}catch(_){ }
    };
    setTimeout(()=>{try{load();}catch(_){ }},0);
  }

  injectStyles();
})();
