from pathlib import Path

runtime = Path('app/static/theme-runtime.js')
s = runtime.read_text()

s = s.replace(
'      body.team-theme-full header.theme-office-logo-active>div:first-child{\n',
'      header.theme-office-logo-active>div:first-child{\n'
)
s = s.replace(
'      body.team-theme-full header.theme-office-logo-active #title{\n',
'      header.theme-office-logo-active #title{\n'
)
s = s.replace(
'      body.team-theme-full header.theme-office-logo-active .subtitle{\n',
'      header.theme-office-logo-active .subtitle{\n'
)

old = '''    injectFrame(theme);\n    if(data.mode==="whole_office") injectOfficeLogo(data,theme);\n\n    const header=document.querySelector("header");\n'''
new = '''    injectFrame(theme);\n\n    const header=document.querySelector("header");\n'''
if old not in s:
    raise SystemExit('office logo inside applyFullTheme not found')
s = s.replace(old,new,1)

old = '''    }else if(data.mode==="whole_office"){\n      const winner=renderedOfficeWinner(data);\n      const winningTheme=winner?lookupTheme(data,winner.team_name,winner.team_id):null;\n      applyFullTheme(data,winningTheme);\n    }else{\n'''
new = '''    }else if(data.mode==="whole_office"){\n      const winner=renderedOfficeWinner(data);\n      const winningTheme=winner?lookupTheme(data,winner.team_name,winner.team_id):null;\n      if(winningTheme) injectOfficeLogo(data,winningTheme);\n      applyFullTheme(data,winningTheme);\n    }else{\n'''
if old not in s:
    raise SystemExit('whole office winning theme block not found')
s = s.replace(old,new,1)

runtime.write_text(s)
Path('VERSION').write_text('51\n')
