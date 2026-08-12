from pathlib import Path
p=Path('.github/scripts/test_v69.js')
s=p.read_text()
s=s.replace("teamData(1,'Alpha',counts[0]||4,9000),teamData(2,'Bravo',counts[1]||4,19000),teamData(3,'Charlie',counts[2]||4,14000)","teamData(1,'Alpha',counts[0]??4,9000),teamData(2,'Bravo',counts[1]??4,19000),teamData(3,'Charlie',counts[2]??4,14000)")
s=s.replace("assert(1080-bottom<22,'Whole Office board does not reach bottom');","assert(1080-bottom<22,`Whole Office board does not reach bottom; bottom=${bottom} gap=${1080-bottom}`);",1)
s=s.replace("assert(1080-bottom<22,'Dense Whole Office board does not reach bottom');","assert(1080-bottom<22,`Dense Whole Office board does not reach bottom; bottom=${bottom} gap=${1080-bottom}`);",1)
p.write_text(s)
