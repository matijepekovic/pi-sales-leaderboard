/* v77 Printer card: find printers on the office network, print a test page. */
(function(){
  const CARD=`
    <div class="card" id="v77PrinterCard">
      <h2>Printer</h2>
      <div class="small">Raw printing on port 9100. If nothing comes out,
        the printer needs CUPS.</div>

      <div style="margin-top:12px">
        <label for="v77PrinterHost">Printer IP address</label>
        <input id="v77PrinterHost" type="text" inputmode="decimal" placeholder="192.168.1.50">
      </div>

      <div class="row" style="margin-top:12px;gap:10px;flex-wrap:wrap">
        <button id="v77PrinterScan" class="btn" type="button">Find Printers</button>
        <button id="v77PrinterTest" class="btn primary" type="button">Print Test Page</button>
      </div>

      <div id="v77PrinterList" style="margin-top:12px"></div>
      <div id="v77PrinterStatus" class="small" style="margin-top:8px"></div>
    </div>`;

  const $=id=>document.getElementById(id);
  const esc=s=>String(s??"").replace(/[&<>"']/g,c=>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  function fillSavedHost(){
    const box=$("v77PrinterHost");
    if(!box||box.value) return;
    if(typeof config!=="undefined"&&config&&config.printer_host){
      box.value=config.printer_host;
    }
  }

  function paintFound(data){
    const box=$("v77PrinterList");
    const printers=(data&&data.printers)||[];
    if(!printers.length){
      box.innerHTML='<div class="small">Nothing answered on port 9100 or 631.</div>';
      return;
    }
    box.innerHTML=printers.map(p=>`
      <div class="row" style="justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid #262626">
        <span>${esc(p.host)} <span class="small">port ${p.ports.join(", ")}</span></span>
        <button class="btn v77Use" type="button" data-host="${esc(p.host)}" data-port="${p.raw?9100:p.ports[0]}">Use</button>
      </div>`).join("");
    box.querySelectorAll(".v77Use").forEach(button=>{
      button.addEventListener("click",()=>{
        $("v77PrinterHost").value=button.dataset.host;
        $("v77PrinterStatus").textContent=
          `Using ${button.dataset.host}. Press Print Test Page.`;
      });
    });
  }

  async function scan(){
    const status=$("v77PrinterStatus"), button=$("v77PrinterScan");
    button.disabled=true;
    status.textContent="Looking across the office network… this takes a few seconds.";
    try{
      const {r,d}=await request("/api/printer/scan",{method:"POST"});
      if(!r.ok||!d.ok){status.textContent=d.error||"Could not scan.";return;}
      paintFound(d);
      status.textContent=`Checked ${esc(d.subnet)} in ${d.seconds}s. `+
        `${d.printers.length} device${d.printers.length===1?"":"s"} answered.`;
    }catch(e){
      if(e.message!=="locked") status.textContent="Could not reach the Pi.";
    }finally{
      button.disabled=false;
    }
  }

  async function printTest(){
    const status=$("v77PrinterStatus"), button=$("v77PrinterTest");
    const host=$("v77PrinterHost").value.trim();
    if(!host){status.textContent="Enter the printer's IP address first.";return;}
    button.disabled=true;
    status.textContent=`Sending a test page to ${host}…`;
    try{
      const {r,d}=await request("/api/printer/test",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({host})});
      status.textContent=(r.ok&&d.ok)?d.message:(d.error||"Could not print.");
      if(r.ok&&d.ok&&typeof config!=="undefined"&&config) config.printer_host=host;
    }catch(e){
      if(e.message!=="locked") status.textContent="Could not reach the Pi.";
    }finally{
      button.disabled=false;
    }
  }

  function mount(){
    const app=document.getElementById("appWrap");
    if(!app||document.getElementById("v77PrinterCard")) return;
    app.insertAdjacentHTML("beforeend",CARD);
    $("v77PrinterScan").addEventListener("click",scan);
    $("v77PrinterTest").addEventListener("click",printTest);
    // config arrives after the page loads; drop the saved address in when it does.
    let tries=0;
    (function attempt(){
      fillSavedHost();
      if(++tries<60 && !$("v77PrinterHost").value) setTimeout(attempt,150);
    })();
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",()=>setTimeout(mount,0));
  }else{
    setTimeout(mount,0);
  }
})();
