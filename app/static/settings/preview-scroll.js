/* v103 iPhone settings preview containment.
   The Check Numbers table is intentionally wider than the phone, but that
   intrinsic width must never widen the settings page itself. Only the preview
   shell may scroll horizontally. */
(function(){
  function install(){
    if(document.getElementById('v103PreviewContainment')) return;
    const style=document.createElement('style');
    style.id='v103PreviewContainment';
    style.textContent=`
      html,body{
        max-width:100%;
        overflow-x:hidden;
      }
      #appWrap,
      #v98Sections,
      .v98-section,
      .v98-section-body,
      .v98-subsection,
      .v98-subsection-body,
      #v90SourceCard,
      #v90SourceCard>section,
      #v79PreviewRows{
        min-width:0!important;
        max-width:100%!important;
      }
      #v79PreviewRows{
        width:100%!important;
        overflow:hidden!important;
      }
      #v79PreviewRows>.v101-number-preview{
        box-sizing:border-box!important;
        display:block!important;
        width:100%!important;
        min-width:0!important;
        max-width:100%!important;
        overflow-x:auto!important;
        overflow-y:auto!important;
        overscroll-behavior:contain;
        -webkit-overflow-scrolling:touch;
        touch-action:pan-x pan-y;
        contain:inline-size;
      }
      #v79PreviewRows>.v101-number-preview>table{
        width:max-content!important;
        min-width:max-content!important;
        max-width:none!important;
      }
    `;
    document.head.appendChild(style);
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install,{once:true});
  else install();
})();
