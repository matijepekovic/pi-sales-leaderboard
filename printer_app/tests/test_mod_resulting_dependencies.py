"""The sheet renderer must be available without optional Gallery/OCR packages."""
from pathlib import Path
import shlex


def test_mod_rasterizer_is_a_required_installer_dependency():
    root = Path(__file__).resolve().parents[2]
    installer = (root / 'printer_app/install.sh').read_text().replace('\\\n', ' ')
    required, optional = installer.split('# Optional gallery tools', 1)
    installs = [shlex.split(line) for line in required.splitlines()
                if 'apt-get install ' in line and not line.lstrip().startswith('#')]
    assert len(installs) == 1
    assert 'poppler-utils' in installs[0]
    assert not any('poppler-utils' in line and 'apt-get install' in line
                   for line in optional.splitlines())
    assert 'command -v pdftoppm >/dev/null' in installer
    assert installer.index('command -v pdftoppm') < installer.index('python3 "$HERE/deploy.py"')


def test_bundled_tests_install_the_real_rasterizer_before_rendering():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / '.github/workflows/bundled-update.yml').read_text()
    dependencies = workflow.split('- name: Independent test dependencies', 1)[1].split(
        '- name: Disposable CI-only printer sinks', 1)[0]
    installs = [shlex.split(line) for line in dependencies.splitlines()
                if 'apt-get install ' in line]
    assert len(installs) == 1 and 'poppler-utils' in installs[0]
    assert 'command -v pdftoppm' in dependencies
