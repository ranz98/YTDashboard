"""Check local prerequisites without claiming work or contacting YouTube."""
import importlib.util
import argparse
import os
from pathlib import Path
import shutil
import subprocess

from runner import BASE, read, validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dependencies-only', action='store_true')
    args = parser.parse_args()
    failures = []
    for executable in ['ffmpeg', 'ffprobe']:
        if not shutil.which(executable):
            failures.append(executable + ' is missing from PATH.')
    for name in ['yt_dlp', 'cv2', 'numpy', 'PIL', 'openai']:
        if importlib.util.find_spec(name) is None:
            failures.append('Missing Python package: ' + name)
    if not args.dependencies_only:
        try:
            validate(read(BASE / 'config.json'))
        except (ValueError, OSError) as error:
            failures.append('Runner configuration: ' + str(error))
    key_path = BASE.parents[1] / 'config/deepseek-key.txt'
    if not args.dependencies_only and not os.environ.get('DEEPSEEK_API_KEY') and not (key_path.exists() and key_path.read_text().strip()):
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
    if not ocr and not (shutil.which('tesseract') and importlib.util.find_spec('pytesseract')):
        failures.append('No working OCR found in this Python. Select the Python used by your existing editor, or configure Windows OCR / Tesseract.')
    for failure in failures:
        print('FIX:', failure)
    if failures:
        print('Nothing was installed or upgraded. Set ASTRA_PYTHON to your working Python path and rerun install.cmd.')
        raise SystemExit(1)
    print('Local checks passed. Chrome pairing and live account access still need the first run.')


if __name__ == '__main__':
    main()
