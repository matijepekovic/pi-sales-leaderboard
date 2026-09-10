/* Settings / Software owns update controls and deployment progress only.
   The printer remains a separately authenticated application on its own port. */
(function(){
  const $=id=>document.getElementById(id);
  let updateAvailable=false;
  let polling=false;

  async function forceManualOnly(){
    const legacy=$('githubAutoUpdate');
    if(legacy) legacy.checked=false;
    try{ if(typeof config==='object'&&config) config.github_auto_update=false; }catch(_){ }
    try{
      await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({github_auto_update:false})});
    }catch(_){ }
  }

  function softwareCard(){
    const anchor=$('softwareVersion')||$('checkGithub')||$('updateFile');
    return anchor?anchor.closest('.card,.v98-inner-card'):null;
  }

  async function waitForRestart(button){
    button.textContent='Restarting…';
    let sawOffline=false;
    for(let i=0;i<75;i++){
      await new Promise(resolve=>setTimeout(resolve,1200));
      try{
        const r=await fetch('/health?ts='+Date.now(),{cache:'no-store'});
        if(r.ok&&(sawOffline||i>4)){location.reload();return;}
      }catch(_){sawOffline=true;}
    }
    button.textContent='Update';
    button.disabled=false;
  }

  function renderDelivery(data){
    const message=$('printerDeliveryStatus');
    if(!message) return;
    message.textContent='Printer app: '+(data.message||data.state||'Checking installation…');
    const link=$('printerDeliveryOpen');
    link.hidden=data.state!=='READY';
    if(!link.hidden){
      const url=new URL(location.href);
      url.protocol='http:';
      url.port=String(data.port||5055);
      url.pathname='/system/print-control';
      url.search='';url.hash='';
      link.href=url.href;
    }
    $('printerDeliveryLogin').hidden=!data.initial_login_available;
    if(data.state==='ERROR'){
      updateAvailable=true;
      $('v107InstallUpdate').disabled=false;
    }
    return data.state==='INSTALLING'||data.state==='QUEUED';
  }

  async function refreshDelivery(){
    if(polling) return;
    polling=true;
    let again=false;
    try{
      const r=await fetch('/api/github/status',{cache:'no-store'});
      if(r.ok) again=renderDelivery((await r.json()).bundled_app||{});
    }catch(_){again=true;}
    finally{polling=false;}
    if(again) setTimeout(refreshDelivery,3000);
  }

  async function credentials(saved=false){
    const r=await fetch('/api/github/printer-login',{method:'POST',
      headers:{'Content-Type':'application/json','X-Requested-With':'Stats-Update'},
      body:JSON.stringify({saved})});
    const d=await r.json();
    if(!r.ok) throw new Error(d.error||'Unlock Settings to view the printer login.');
    return d;
  }

  function install(){
    const card=softwareCard();
    if(!card) return false;
    if($('v107SoftwareManual')) return true;
    // Preserve the existing base-page elements its initialization still uses.
    Array.from(card.children).forEach(child=>{if(child.tagName!=='H2') child.style.display='none';});
    const box=document.createElement('div');
    box.id='v107SoftwareManual';
    box.innerHTML=`
      <div class="row">
        <button id="v107CheckUpdate" class="btn" type="button">Check for Updates</button>
        <button id="v107InstallUpdate" class="btn primary" type="button" disabled>Update</button>
      </div>
      <p id="printerDeliveryStatus" class="small" role="status"></p>
      <div class="row">
        <a id="printerDeliveryOpen" class="btn" target="_blank" rel="noopener noreferrer" hidden>Open Print Control</a>
        <button id="printerDeliveryLogin" class="btn" type="button" hidden>Show printer login</button>
        <button id="printerDeliverySaved" class="btn" type="button" hidden>I saved the login</button>
      </div>
      <p id="printerDeliveryCredentials" class="small" role="status"></p>`;
    card.appendChild(box);
    const check=$('v107CheckUpdate'),update=$('v107InstallUpdate');
    check.addEventListener('click',async()=>{
      updateAvailable=false;check.disabled=true;update.disabled=true;check.textContent='Checking…';
      try{
        const r=await fetch('/api/github/available',{cache:'no-store'}),d=await r.json();
        if(!r.ok) throw new Error(d.error||'Check failed');
        updateAvailable=Boolean(d.stats_update_available||d.printer_update_available);
        check.textContent=updateAvailable?'Update Available':'Up to Date';
        update.disabled=!updateAvailable;
        renderDelivery(d.bundled_app||{});
      }catch(e){check.textContent='Check Failed';$('printerDeliveryStatus').textContent=e.message;}
      finally{check.disabled=false;}
    });
    update.addEventListener('click',async()=>{
      if(!updateAvailable) return;
      check.disabled=true;update.disabled=true;update.textContent='Updating…';
      try{
        const r=await fetch('/api/github/check',{method:'POST'}),d=await r.json();
        if(!r.ok) throw new Error(d.error||'Update failed');
        if(d.installed){await waitForRestart(update);return;}
        updateAvailable=false;
        check.textContent='Check for Updates';
        renderDelivery(d.bundled_app||{});
        refreshDelivery();
      }catch(e){
        $('printerDeliveryStatus').textContent=e.message;
        updateAvailable=true;
      }finally{
        update.textContent='Update';update.disabled=!updateAvailable;check.disabled=false;
      }
    });
    $('printerDeliveryLogin').addEventListener('click',async()=>{
      const output=$('printerDeliveryCredentials');
      try{
        const d=await credentials();
        output.textContent='Printer username: '+d.login.username+' — Password: '+d.login.password;
        $('printerDeliverySaved').hidden=false;
      }catch(e){output.textContent=e.message;}
    });
    $('printerDeliverySaved').addEventListener('click',async()=>{
      try{
        await credentials(true);
        $('printerDeliveryCredentials').textContent='Initial login removed from the update page. Your printer login still works.';
        $('printerDeliverySaved').hidden=true;
        refreshDelivery();
      }catch(e){$('printerDeliveryCredentials').textContent=e.message;}
    });
    // Do not leave initial credentials visible on a hidden or locked page.
    $('lockNow')?.addEventListener('click',()=>{$('printerDeliveryCredentials').textContent='';});
    document.addEventListener('visibilitychange',()=>{
      if(document.hidden) $('printerDeliveryCredentials').textContent='';
    });
    forceManualOnly();
    setTimeout(forceManualOnly,500);setTimeout(forceManualOnly,1500);setTimeout(forceManualOnly,3000);
    refreshDelivery();
    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){if(install()) return;if(++tries<80) setTimeout(attempt,50);})();
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();
