"""CI-only Pi-style upgrade smoke test. Uses an isolated CUPS file sink, never hardware.

Run on the disposable runner as scoreboard with the old server file and a new
update ZIP. The source revision argument substitutes for main during pre-merge
validation; the production source selector is otherwise exercised unchanged.
"""
import ast
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile


def run(*command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def wait_health(port):
    for _ in range(120):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(1)
    raise AssertionError('Service did not become healthy on port ' + str(port))


def pid(unit):
    return subprocess.check_output(['systemctl','show','--property=MainPID','--value',unit], text=True).strip()


def main():
    new_source, legacy_server, source_ref, printer_tree = map(str, sys.argv[1:])
    source = Path(new_source)
    installed = Path.home() / 'delivery-smoke/stats'
    installed.mkdir(parents=True)
    # The legacy installed footprint deliberately has no printer_app or .git.
    shutil.copytree(source/'app', installed/'app')
    shutil.copy2(legacy_server, installed/'app/server.py')
    (installed/'app/update_delivery.py').unlink()
    shutil.copy2(source/'requirements.txt', installed/'requirements.txt')
    shutil.copy2(source/'kiosk.sh', installed/'kiosk.sh')
    (installed/'VERSION').write_text('133\n')
    run('/usr/bin/python3','-m','venv',str(installed/'.venv'))
    run(str(installed/'.venv/bin/pip'),'install','-r',str(installed/'requirements.txt'))
    service = (source/'pi-tableau-leaderboard.service').read_text()
    service = service.replace('__USER__','scoreboard').replace('__APPDIR__',str(installed)).replace('__VENV__',str(installed/'.venv'))
    unit_file = installed.parent/'pi-tableau-leaderboard.service'
    unit_file.write_text(service)
    run('sudo','-n','install','-m','0644',str(unit_file),'/etc/systemd/system/pi-tableau-leaderboard.service')
    run('sudo','-n','systemctl','daemon-reload')
    run('sudo','-n','systemctl','start','pi-tableau-leaderboard.service')
    wait_health(8765)
    original_pid = pid('pi-tableau-leaderboard.service')
    # Execute the actual previously shipped ZIP installer, not a rewritten model.
    nodes = [n for n in ast.parse(Path(legacy_server).read_text()).body if isinstance(n, ast.FunctionDef)
             and n.name in {'_safe_zip_member','_find_update_root','install_update_zip'}]
    namespace = dict(Path=Path, APP_ROOT=installed, UPDATE_DIR=installed.parent/'updates',
                     tempfile=tempfile, shutil=shutil, zipfile=zipfile, time=time, subprocess=subprocess)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'legacy-updater','exec'),namespace)
    package = installed.parent/'update.zip'
    with zipfile.ZipFile(package,'w') as z:
        for path in source.rglob('*'):
            relative = path.relative_to(source)
            if path.is_file() and not any(p in ('.git','.venv','__pycache__','.pytest_cache') for p in relative.parts):
                z.write(path,'package/'+relative.as_posix())
    namespace['install_update_zip'](package)
    assert not (installed/'printer_app').exists()
    assert pid('pi-tableau-leaderboard.service') == original_pid
    assert (installed/'VERSION').read_text().strip() == '134'
    spec = importlib.util.spec_from_file_location('delivery', installed/'app/update_delivery.py')
    delivery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(delivery)
    selected = delivery.remote_bundle(source_ref)
    assert selected['tree'] == printer_tree
    original_request = delivery.request_install
    # During CI main still points at the previous release. Select the exact PR
    # tree, then execute the same first-start handoff into real detached systemd.
    delivery.request_install = lambda **kw: original_request(selected, **kw)
    delivery.start_initial_install()
    assert delivery.status()['state'] in ('QUEUED','INSTALLING')
    run('sudo','-n','systemctl','stop','pi-tableau-leaderboard.service')
    hidden = installed.with_name('stats-offline')
    installed.rename(hidden)
    for _ in range(360):
        state = delivery.status()
        if state['state'] in ('READY','ERROR'):
            break
        time.sleep(1)
    assert state['state'] == 'READY', state
    wait_health(5055)
    assert pid('pi-tableau-leaderboard.service') == '0'
    assert (Path.home()/'.config/printer-app/env').is_file()
    assert not (hidden/'printer_app').exists()
    # Installed source and both printer processes must survive removal of Stats.
    web_pid, worker_pid = pid('printer-app-web.service'), pid('printer-app-worker.service')
    assert web_pid != '0' and worker_pid != '0'
    hidden.rename(installed)
    run('sudo','-n','systemctl','start','pi-tableau-leaderboard.service')
    wait_health(8765)
    stats_pid = pid('pi-tableau-leaderboard.service')
    for route in ('/','/settings','/api/leaderboard','/api/config'):
        with urllib.request.urlopen('http://127.0.0.1:8765'+route) as response:
            assert response.status == 200
    assert original_request(selected)['state'] == 'READY'
    time.sleep(1)
    assert pid('pi-tableau-leaderboard.service') == stats_pid
    assert pid('printer-app-web.service') == web_pid
    assert pid('printer-app-worker.service') == worker_pid
    assert Path('/etc/systemd/system/pi-tableau-leaderboard.service').read_text() == service
    run('sudo','-n','systemctl','stop','printer-app-web.service','printer-app-worker.service')
    wait_health(8765)
    assert pid('pi-tableau-leaderboard.service') == stats_pid
    run('sudo','-n','systemctl','start','printer-app-web.service','printer-app-worker.service')
    wait_health(5055)
    assert subprocess.check_output(['systemctl','is-enabled','printer-app-web.service'],text=True).strip() == 'enabled'
    assert subprocess.check_output(['systemctl','is-enabled','printer-app-worker.service'],text=True).strip() == 'enabled'
    print('PASS: old ZIP updater → detached printer install → independent Stats/printer lifecycles; unchanged update is a no-op.')


if __name__ == '__main__':
    main()
