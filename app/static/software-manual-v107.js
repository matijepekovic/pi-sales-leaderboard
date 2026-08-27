/* Software stays user-controlled: Check for Updates + Update.
   On the packaged Windows build, both actions go through the signed public
   installer update API. Download, signature/hash verification, silent install,
   shutdown, and relaunch happen automatically after Update is pressed. */
(function(){
  const $=id=>document.getElementById(id);
  let remoteVersion=null;

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
    button.textContent='Installing…';
    let sawOffline=false;
    for(let i=0;i<100;i++){
      await new Promise(resolve=>setTimeout(resolve,1200));
      try{
        const r=await fetch('/health?ts='+Date.now(),{cache:'no-store'});
        if(r.ok&&(sawOffline||i>8)){
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
        const r=await fetch('/api/windows/update/check',{
          method:'POST',
          cache:'no-store'
        });
        const d=await r.json();
        if(!r.ok||!d.ok) throw new Error(d.error||'check failed');
        if(d.available){
          remoteVersion=String(d.latest||'');
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
      update.textContent='Downloading…';
      try{
        const r=await fetch('/api/windows/update/install',{
          method:'POST',
          cache:'no-store'
        });
        const d=await r.json();
        if(!r.ok||!d.ok) throw new Error(d.error||'update failed');
        if(d.installed||d.installing){
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
