import {request,json} from "./workspace/runtime.js";
import {createDataWorkspace} from "./workspace/data.js";
import {createFiltersWorkspace} from "./workspace/filters.js";
import {createScreensWorkspace} from "./workspace/screens.js";
import {createDisplayWorkspace} from "./workspace/display.js";

const lock=document.getElementById("settingsLock");
const app=document.getElementById("settingsApp");
const message=document.getElementById("globalMessage");
const title=document.getElementById("sectionTitle");
const nav=document.getElementById("settingsNav");
let active="data";
const loaded=new Set();

function notify(text="",error=false){message.textContent=text;message.classList.toggle("error",!!error);message.classList.toggle("ok",!!text&&!error);}
function host(name){return document.querySelector(`[data-workspace="${name}"]`);}

let screens,display;
const data=createDataWorkspace({host:host("data"),notify,onChanged:()=>{loaded.delete("filters");loaded.delete("screens");}});
const filters=createFiltersWorkspace({host:host("filters"),notify,onChanged:()=>{loaded.delete("screens");}});
screens=createScreensWorkspace({host:host("screens"),notify,onChanged:()=>{loaded.delete("display");},filterManager:filters});
display=createDisplayWorkspace({host:host("display"),notify});
const modules={data,filters,screens,display};

async function show(name){
  if(!modules[name])return;active=name;
  document.querySelectorAll(".workspace").forEach(section=>section.classList.toggle("active",section.dataset.workspace===name));
  nav.querySelectorAll("button[data-section]").forEach(button=>button.classList.toggle("active",button.dataset.section===name));
  title.textContent=name.charAt(0).toUpperCase()+name.slice(1);notify("");
  try{await modules[name].load();loaded.add(name);}catch(error){notify(error.message,true);}
}

async function authState(){
  try{const status=await request("/api/auth/status");if(status.unlocked){lock.hidden=true;app.hidden=false;await show(active);return}lock.hidden=false;app.hidden=true;}catch(error){lock.hidden=false;app.hidden=true;document.getElementById("unlockMessage").textContent=error.message;}
}

nav.addEventListener("click",event=>{const button=event.target.closest("button[data-section]");if(button)show(button.dataset.section);});
document.getElementById("unlockForm").addEventListener("submit",async event=>{event.preventDefault();const box=document.getElementById("unlockMessage"),pin=document.getElementById("unlockPin").value;box.textContent="Checking…";try{await request("/api/auth/unlock",json("POST",{pin}));document.getElementById("unlockPin").value="";box.textContent="";lock.hidden=true;app.hidden=false;await show(active);}catch(error){box.textContent=error.message;}});
document.getElementById("lockSettings").addEventListener("click",async()=>{try{await request("/api/auth/lock",{method:"POST"});}catch(_){ }app.hidden=true;lock.hidden=false;document.getElementById("unlockPin").focus();});

request("/api/system/version").then(data=>{document.getElementById("versionText").textContent=`Stats ${data.version||""}`;}).catch(()=>{});
authState();
