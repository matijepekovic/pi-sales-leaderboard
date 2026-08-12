from pathlib import Path
p=Path('app/static/whole-office-inline-team-v57.js')
s=p.read_text()
old='''    #v55OfficeBroadcast .v55-office-row{
      height:clamp(34px,3.05vh,70px)!important;
    }
    #v55OfficeBroadcast .v55-office-row.champion{
      height:clamp(42px,3.70vh,86px)!important;
    }
'''
if old in s:
    s=s.replace(old,'',1)
elif 'height:clamp(34px,3.05vh,70px)!important' in s:
    raise SystemExit('v57 height override pattern changed')
p.write_text(s)
p=Path('app/templates/display.html')
s=p.read_text().replace('whole-office-inline-team-v57.js?v=57','whole-office-inline-team-v57.js?v=69')
p.write_text(s)
