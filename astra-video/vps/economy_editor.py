"""Apply API spending limits while leaving original editor files untouched."""
import hashlib
import importlib
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

MODEL = 'deepseek-flash'
MAX_TOKENS = 256


def install_limits(module, cache_dir):
    original_client = module._deepseek_client
    original_rewrite = module.rewrite_caption
    cache_dir.mkdir(parents=True, exist_ok=True)
    calls = 0

    def client(api_key):
        underlying = original_client(api_key).with_options(max_retries=0)

        def create(**request):
            nonlocal calls
            request.update(model=MODEL, max_tokens=MAX_TOKENS,
                           extra_body={'thinking': {'type': 'disabled'}})
            key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
            path = cache_dir / (key + '.json')
            if path.exists():
                content = json.loads(path.read_text(encoding='utf-8'))['content']
                print('  DeepSeek: reused a saved rewrite; no API call.', flush=True)
            else:
                if calls >= 2:
                    raise RuntimeError('Economy limit reached: two API requests per editor run.')
                calls += 1
                response = underlying.chat.completions.create(**request)
                choice = response.choices[0]
                if choice.finish_reason != 'stop' or not choice.message.content:
                    raise RuntimeError('Rewrite incomplete; no automatic paid retry.')
                content = choice.message.content
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'content': content}), encoding='utf-8')
                temporary.replace(path)
                print('  DeepSeek: Flash, thinking off, one request.', flush=True)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def rewrite(*args, **kwargs):
        kwargs.update(attempts=1, model=MODEL)
        return original_rewrite(*args, **kwargs)

    module._deepseek_client = client
    module.rewrite_caption = rewrite


def main():
    editor = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(editor.parent))
    module = importlib.import_module('caption_text')
    install_limits(module, Path(__file__).resolve().parent / 'data/rewrite-cache')
    sys.argv = [str(editor), *sys.argv[2:]]
    runpy.run_path(str(editor), run_name='__main__')


if __name__ == '__main__':
    main()
