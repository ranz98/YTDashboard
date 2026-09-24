"""Exercise the same OCR path as the editor without downloading or posting."""
import argparse
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path)
    parser.add_argument('--editor', type=Path, default=Path(__file__).resolve().parent / 'original-editor/cover_caption.py')
    args = parser.parse_args()
    import importlib.util
    sys.path.insert(0, str(args.editor.resolve().parent))
    spec = importlib.util.spec_from_file_location('cover_caption', args.editor)
    cover_caption = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cover_caption)
    from PIL import Image, ImageDraw, ImageFont
    with tempfile.TemporaryDirectory(prefix='astra-ocr-') as directory:
        path = args.image.resolve() if args.image else Path(directory) / 'sample.png'
        if not args.image:
            image = Image.new('RGB', (700, 130), 'white')
            font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 48)
            ImageDraw.Draw(image).text((20, 25), 'ASTRA VIDEO TEST 123', fill='black', font=font)
            image.save(path)
        lines = cover_caption.ocr_windows(path) or cover_caption.ocr_tesseract(path)
        text = ' '.join(lines or [])
        print('OCR result:', text or '(no text)')
        if not text or (not args.image and 'ASTRA' not in text.upper()):
            print('OCR check failed. The errors above identify the engine failure; no packages were changed.')
            return 1
        print('OCR check passed.')
        return 0


if __name__ == '__main__':
    sys.exit(main())
