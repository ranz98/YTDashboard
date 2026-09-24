"""Check local prerequisites without claiming work or contacting YouTube."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

from runner import BASE, read, validate


def main():
    failures = []
    for executable in ['ffmpeg', 'ffprobe', 'node']:
        if not shutil.which(executable):
            failures.append(executable + ' is missing from PATH.')
    if shutil.which('node'):
        version = subprocess.check_output(['node', '--version'], text=True).strip()
        if int(version.lstrip('v').split('.')[0]) < 22:
            failures.append('Node.js 22 or newer is required.')
    for name in ['yt_dlp', 'cv2', 'numpy', 'PIL', 'openai', 'pytesseract']:
        if importlib.util.find_spec(name) is None:
            failures.append('Missing Python package: ' + name)
    try:
        validate(read(BASE / 'config.json'))
    except (ValueError, OSError) as error:
        failures.append('Runner configuration: ' + str(error))
    key_path = BASE.parents[1] / 'config/deepseek-key.txt'
    if not os.environ.get('DEEPSEEK_API_KEY') and not (key_path.exists() and key_path.read_text().strip()):
        failures.append('Put your DeepSeek key in config/deepseek-key.txt under the main Astra folder.')
    ocr = False
    try:
        try:
            from winrt.windows.media.ocr import OcrEngine
        except ImportError:
            from winsdk.windows.media.ocr import OcrEngine
        ocr = OcrEngine.try_create_from_user_profile_languages() is not None
    except Exception:
        pass
    if not ocr and not shutil.which('tesseract'):
        failures.append('Windows OCR is unavailable. Install Tesseract with English data and add it to PATH.')
    for failure in failures:
        print('FIX:', failure)
    if failures:
        raise SystemExit(1)
    print('Local checks passed. Chrome pairing and live account access still need the first run.')


if __name__ == '__main__':
    main()
