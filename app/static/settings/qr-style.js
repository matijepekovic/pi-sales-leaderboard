/* v113: one permanent QR appearance in the remote preview. */
(function(){
  function apply(){
    const preview=document.getElementById('v110QrPreview');
    if(!preview) return false;
    preview.style.background='#000';
    preview.style.borderRadius='7px';
    preview.style.boxShadow='0 0 0 1px rgba(255,255,255,.10)';
    const image=preview.querySelector('img');
    if(image){
      image.src='/static/remote-qr-v109.svg?v=113';
      image.style.borderRadius='4px';
    }
    return true;
  }

  let tries=0;
  (function attempt(){
    if(apply()) return;
    if(++tries<120) setTimeout(attempt,50);
  })();
})();
