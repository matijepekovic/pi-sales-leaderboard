/* Production Settings navigation + neutral Tableau connection examples. */
(function(){
  const EXAMPLES={
    v90Server:'Example: https://your-pod.online.tableau.com',
    v90Site:'Example: your-site',
    v90PatName:'Example: stats-pat'
  };

  function addBackButton(){
    const app=document.getElementById('appWrap');
    if(!app||document.getElementById('backToStats')) return !!app;

    const row=document.createElement('div');
    row.id='statsSettingsBackRow';
    row.style.cssText='display:flex;justify-content:flex-start;margin:0 0 12px';

    const button=document.createElement('button');
    button.id='backToStats';
    button.type='button';
    button.className='btn';
    button.textContent='← Back to Stats';
    button.setAttribute('aria-label','Back to Stats');
    button.addEventListener('click',()=>window.location.assign('/'));

    row.appendChild(button);
    app.insertBefore(row,app.firstChild);
    return true;
  }

  function applyExamples(){
    let found=0;
    Object.entries(EXAMPLES).forEach(([id,placeholder])=>{
      const input=document.getElementById(id);
      if(!input) return;
      input.placeholder=placeholder;
      found+=1;
    });
    return found===Object.keys(EXAMPLES).length;
  }

  function apply(){
    return addBackButton()&&applyExamples();
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(apply()) return;
      if(++tries<60) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start,{once:true});
  else start();
})();
