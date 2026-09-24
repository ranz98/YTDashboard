"""Build a portable source bundle without credentials or generated media."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
VPS = ROOT / 'astra-video/vps'


def build():
    output = ROOT / 'astra-video/data/releases/Astra-Windows-VPS.zip'
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [*VPS.glob('*.py'), *VPS.glob('*.cmd'), *VPS.glob('*.ps1'),
             VPS / 'requirements.txt', VPS / 'config.example.json', VPS / 'WINDOWS-SETUP.md',
             *VPS.glob('extension/*.js'), *VPS.glob('extension/*.html'),
             *VPS.glob('extension/*.css'), VPS / 'extension/manifest.json',
             ROOT / 'scripts/cover_caption.py', ROOT / 'scripts/caption_text.py',
             *ROOT.glob('assets/fonts/*'), ROOT / 'config/deepseek-key.example.txt']
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, 'ASTRA/' + path.relative_to(ROOT).as_posix())
        archive.write(VPS / 'WINDOWS-SETUP.md', 'ASTRA/START-HERE.md')
    print(output)
    return output


if __name__ == '__main__':
    build()
