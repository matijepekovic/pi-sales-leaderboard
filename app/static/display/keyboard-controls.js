/* Physical controls: keyboard, mouse and macro pad.

   This file used to own the rotation itself -- which screen was showing, which
   team pair, which sort column, and a five minute idle timer -- inside a
   closure. That made the steer private to one tab: a second display never saw
   it, a reload lost it, and the list of screens had to be repeated here so the
   closure could walk it.

   The server owns that state now. This file recognises an input, names the
   action, and posts it. The key map and the action list come from the server
   too, so there is one definition of each. */
(function(){
  let keys=null;
  let lastWheelAt=0;

  function keyToken(value){
    value=String(value??"");
    return value.length===1&&value!==" "?value.toLowerCase():value;
  }

  async function refreshVocabulary(){
    try{
      const response=await fetch("/api/keyboard-controls",{cache:"no-store"});
      if(!response.ok) throw new Error("controls");
      const payload=await response.json();
      const map=payload?.keyboard?.keys;
      if(map&&typeof map==="object"){
        const resolved={};
        for(const action of Object.keys(map)) resolved[action]=keyToken(map[action]);
        keys=resolved;
      }
    }catch(_){ /* keep the last known map rather than going deaf */ }
    return keys;
  }

  function actionForInput(input){
    if(!keys) return null;
    for(const action of Object.keys(keys)){
      if(keys[action]===input) return action;
    }
    return null;
  }

  function forceReload(){
    try{ if(typeof lastSignature!=="undefined") lastSignature=""; }catch(_){}
    if(typeof load==="function") load();
  }

  async function act(action){
    try{
      const response=await fetch("/api/controls/action",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        cache:"no-store",
        body:JSON.stringify({action})
      });
      if(!response.ok) return false;
      const payload=await response.json();
      if(payload?.state?.changed) forceReload();
      return true;
    }catch(_){
      return false;
    }
  }

  document.addEventListener("keydown",event=>{
    if(event.repeat) return;
    const action=actionForInput(keyToken(event.key));
    if(!action) return;
    event.preventDefault();
    act(action);
  },true);

  window.addEventListener("wheel",event=>{
    if(!event.deltaY) return;
    const action=actionForInput(event.deltaY<0?"MouseWheelUp":"MouseWheelDown");
    if(!action) return;
    event.preventDefault();
    // The pad emits a burst of wheel events per detent; one step per detent.
    const now=Date.now();
    if(now-lastWheelAt<55) return;
    lastWheelAt=now;
    act(action);
  },{passive:false,capture:true});

  document.addEventListener("mousedown",event=>{
    const token=event.button===0?"MouseLeft":event.button===1?"MouseMiddle":event.button===2?"MouseRight":null;
    if(!token) return;
    const action=actionForInput(token);
    if(!action) return;
    event.preventDefault();
    act(action);
  },true);

  document.addEventListener("contextmenu",event=>{
    if(actionForInput("MouseRight")) event.preventDefault();
  },true);

  refreshVocabulary();
  setInterval(refreshVocabulary,5000);
})();
