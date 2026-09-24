"""Build a portable source bundle without credentials or generated media."""
from pathlib import Path
import zipfile
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
VPS = ROOT / 'astra-video/vps'


def build():
    hashes = json.loads((VPS / 'original-editor-sha256.json').read_text())
    for name, expected in hashes.items():
        if hashlib.sha256((VPS / 'original-editor' / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Original editor file changed: ' + name)
    output = ROOT / 'astra-video/data/releases/Astra-Windows-VPS.zip'
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [*VPS.glob('*.py'), *VPS.glob('*.cmd'), *VPS.glob('*.ps1'),
             VPS / 'requirements.txt', VPS / 'config.example.json', VPS / 'WINDOWS-SETUP.md', VPS / 'original-editor-sha256.json',
             *VPS.glob('extension/*.js'), *VPS.glob('extension/*.html'),
             *VPS.glob('extension/*.css'), VPS / 'extension/manifest.json',
             VPS / 'original-editor/cover_caption.py', VPS / 'original-editor/caption_text.py',
             VPS / 'original-editor/edit_pending.py',
             VPS / 'original-editor/fonts/Montserrat[wght].ttf', VPS / 'original-editor/fonts/OFL.txt',
             ROOT / 'config/deepseek-key.example.txt']
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, 'ASTRA/' + path.relative_to(ROOT).as_posix())
        archive.write(VPS / 'WINDOWS-SETUP.md', 'ASTRA/START-HERE.md')
    print(output)
    return output


if __name__ == '__main__':
    build()
