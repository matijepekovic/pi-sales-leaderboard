/* v107: Software is manual-only.
   Production uses semantic versions and checks only the production branch.
   Legacy ZIP upload / version / status / automatic-update controls stay in the
   DOM only so the older base script can finish safely, but they are hidden.
   Any previously saved automatic-update preference is forced off. */
(function(){
  const $=id=>document.getElementById(id);
  const REMOTE_VERSION_URL='https://raw.githubusercontent.com/matijepekovic/pi-sales-leaderboard/production/VERSION';
  let remoteVersion=null;

  function versionKey(value){
    const parts=String(value||'').match(/\d+/g)||[];
    return parts.map(Number);
  }

  function compareVersions(a,b){
    const left=versionKey(a),right=versionKey(b);
    const n=Math.max(left.length,right.length);
    for(let i=0;i<n;i++){
      const av=left[i]||0,bv=right[i]||0;
      if(av!==bv) return av>bv?1:-1;
    }
    return 0;
  }

  async function forceManualOnly(){
    const legacy=$('githubAutoUpdate');
    if(legacy) legacy.checked=false;
    try{
      if(typeof config==='object'&&config) config.github_auto_update=false;
    }catch(_){ }
    try{
      await fetch('/api/config',{
        method:'PUT',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({github_auto_update:false})
      });
    }catch(_){ }
  }

  function softwareCard(){
    const anchor=$('softwareVersion')||$('checkGithub')||$('updateFile');
    if(!anchor) return null;
    return anchor.closest('.card,.v98-inner-card');
  }

  async function waitForRestart(button){
    button.textContent='Restarting…';
    let sawOffline=false;
    for(let i=0;i<75;i++){
      await new Promise(resolve=>setTimeout(resolve,1200));
      try{
        const r=await fetch('/health?ts='+Date.now(),{cache:'no-store'});
        if(r.ok&&(sawOffline||i>4)){
          location.reload();
          return;
        }
      }catch(_){
        sawOffline=true;
      }
    }
    button.textContent='Update';
    button.disabled=false;
  }

  function install(){
    const card=softwareCard();
    if(!card) return false;
    if($('v107SoftwareManual')) return true;

    // Keep the heading so the accordion can still discover/name the section.
    Array.from(card.children).forEach(child=>{
      if(child.tagName!=='H2') child.style.display='none';
    });

    const box=document.createElement('div');
    box.id='v107SoftwareManual';
    box.style.display='flex';
    box.style.gap='10px';
    box.style.flexWrap='wrap';
    box.innerHTML=`
      <button id="v107CheckUpdate" class="btn" type="button">Check for Updates</button>
      <button id="v107InstallUpdate" class="btn primary" type="button" disabled>Update</button>`;
    card.appendChild(box);

    const check=$('v107CheckUpdate');
    const update=$('v107InstallUpdate');

    check.addEventListener('click',async()=>{
      remoteVersion=null;
      check.disabled=true;
      update.disabled=true;
      check.textContent='Checking…';
      try{
        const [localResponse,remoteResponse]=await Promise.all([
          fetch('/api/system/version',{cache:'no-store'}),
          fetch(REMOTE_VERSION_URL+'?ts='+Date.now(),{cache:'no-store'})
        ]);
        if(!localResponse.ok||!remoteResponse.ok) throw new Error('check failed');
        const local=String((await localResponse.json()).version||'');
        const remote=String(await remoteResponse.text()).trim();
        if(compareVersions(remote,local)>0){
          remoteVersion=remote;
          check.textContent='Update Available';
          update.disabled=false;
        }else{
          check.textContent='Up to Date';
          setTimeout(()=>{check.textContent='Check for Updates';},1600);
        }
      }catch(_){
        check.textContent='Check Failed';
        setTimeout(()=>{check.textContent='Check for Updates';},1800);
      }finally{
        check.disabled=false;
      }
    });

    update.addEventListener('click',async()=>{
      if(!remoteVersion) return;
      check.disabled=true;
      update.disabled=true;
      update.textContent='Updating…';
      try{
        const r=await fetch('/api/github/check',{method:'POST'});
        const d=await r.json();
        if(!r.ok) throw new Error(d.error||'update failed');
        if(d.installed){
          await waitForRestart(update);
          return;
        }
        remoteVersion=null;
        update.textContent='Update';
        update.disabled=true;
        check.textContent='Up to Date';
        setTimeout(()=>{check.textContent='Check for Updates';},1600);
      }catch(_){
        update.textContent='Update Failed';
        setTimeout(()=>{
          update.textContent='Update';
          update.disabled=!remoteVersion;
          check.disabled=false;
        },1800);
      }
    });

    // The old page can populate the hidden checkbox slightly after this patch
    // runs. Clear it again after the base load settles, and persist false.
    forceManualOnly();
    setTimeout(forceManualOnly,500);
    setTimeout(forceManualOnly,1500);
    setTimeout(forceManualOnly,3000);
    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(install()) return;
      if(++tries<80) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();
