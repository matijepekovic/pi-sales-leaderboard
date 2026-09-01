/* Shared runtime contract for Settings modules. */
(function(){
  const listeners=new Map();
  const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));

  async function api(url,options={}){
    const headers={...(options.headers||{})};
    if(options.body && !(options.body instanceof FormData) && !headers["Content-Type"]){
      headers["Content-Type"]="application/json";
    }
    const response=await fetch(url,{cache:"no-store",...options,headers});
    const data=await response.json().catch(()=>({}));
    if(response.status===401 && data.locked){
      document.dispatchEvent(new CustomEvent("stats:settings-locked"));
      throw new Error("Settings are locked.");
    }
    if(!response.ok || data.ok===false) throw new Error(data.error||`Request failed (${response.status})`);
    return data;
  }

  function json(method,body){
    return {method,body:JSON.stringify(body||{})};
  }

  function on(name,callback){
    if(!listeners.has(name)) listeners.set(name,new Set());
    listeners.get(name).add(callback);
    return ()=>listeners.get(name)?.delete(callback);
  }

  function emit(name,detail){
    for(const callback of listeners.get(name)||[]){
      try{callback(detail);}catch(error){console.error(error);}
    }
  }

  window.StatsSettings=Object.freeze({api,json,esc,on,emit});
})();
