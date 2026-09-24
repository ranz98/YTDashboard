"""Fetch, edit and upload adapters for the Windows runner."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from runner import BASE, read, save

ROOT = BASE.parents[1]


def progress(path, percent, message):
    save(path.parent / 'progress.json', {'progress': percent, 'message': message})


def browser(action, **payload):
    command = dict(payload, id=uuid.uuid4().hex, action=action)
    request = BASE / 'data/browser-command.json'
    response = BASE / 'data/browser-result.json'
    if request.exists():
        raise RuntimeError('An earlier browser command needs review.')
    response.unlink(missing_ok=True)
    save(request, command)
    deadline = time.monotonic() + 6500
    while time.monotonic() < deadline:
        if response.exists():
            result = read(response)
            if result.get('id') == command['id']:
                request.unlink(missing_ok=True)
                if not result.get('ok'):
                    raise RuntimeError(result.get('error', 'Chrome operation failed.'))
                return result
        time.sleep(1)
    raise TimeoutError('Chrome operation timed out.')


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)


def verify(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                             '-of', 'json', str(path)], check=True, capture_output=True, text=True)
    media = json.loads(result.stdout)
    if not any(s.get('codec_type') == 'video' for s in media.get('streams', [])):
        raise RuntimeError('No video stream found.')
    duration = float(media.get('format', {}).get('duration', 0))
    if duration <= 0 or path.stat().st_size < 1024:
        raise RuntimeError('The media file is incomplete.')
    return duration


def folder_for(task, video_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise ValueError('Invalid video ID.')
    return BASE / 'data/media' / str(int(task['channel_id'])) / video_id


def fetch(task, request):
    progress(request, 5, 'Chrome is checking the latest five Shorts.')
    scan = browser('fetch', handle=task['channel']['handle'])['videos']
    if not isinstance(scan, list) or len(scan) > 5:
        raise ValueError('Invalid channel scan.')
    videos, seen = [], set()
    for index, video in enumerate(scan):
        video_id = video['id']
        folder = folder_for(task, video_id)
        if video_id in seen:
            continue
        seen.add(video_id)
        item = {'id': video_id, 'title': str(video.get('title') or video_id)}
        if video_id in task.get('known_video_ids', []):
            videos.append(dict(item, downloaded=False, reason='Already in the queue.'))
            continue
        folder.mkdir(parents=True, exist_ok=True)
        progress(request, 10 + index * 16, 'Downloading video %s of %s.' % (index + 1, len(scan)))
        media = folder / 'video.mp4'
        try:
            if not media.exists():
                run(sys.executable, '-m', 'yt_dlp', '--no-playlist', '--merge-output-format', 'mp4',
                    '--js-runtimes', 'node',
                    '-f', 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best',
                    '-o', folder / 'video.%(ext)s', 'https://www.youtube.com/watch?v=' + video_id)
            verify(media)
            run('ffmpeg', '-y', '-v', 'error', '-i', media, '-frames:v', '1', folder / 'frame.jpg')
            (folder / 'title.txt').write_text(item['title'], encoding='utf-8')
            videos.append(dict(item, downloaded=True))
        except (subprocess.CalledProcessError, RuntimeError, FileNotFoundError):
            videos.append(dict(item, downloaded=False, reason='Download verification failed; inspect the VPS log.'))
    return {'state': 'completed', 'videos': videos}


def edit(task, request):
    folder = folder_for(task, task['video']['source_video_id'])
    source = folder / 'video.mp4'
    duration = verify(source)
    output = folder / 'render.mp4'
    temporary = folder / 'render-working.mp4'
    # Keep source selection deterministic when an edit is retried.
    progress(request, 15, 'Rewriting the caption and rendering the video.')
    (folder / 'title-new.txt').unlink(missing_ok=True)
    run(sys.executable, ROOT / 'scripts/cover_caption.py', source, '--rewrite', '--no-stage',
        '--filter', task['channel'].get('preset') or 'vivid', '-o', temporary)
    rendered = verify(temporary)
    run('ffmpeg', '-v', 'error', '-xerror', '-i', temporary, '-f', 'null', '-')
    if abs(duration - rendered) > max(1.0, duration * .02):
        raise RuntimeError('Rendered duration does not match the source.')
    title = (folder / 'title-new.txt').read_text(encoding='utf-8').strip()
    if not title or len(title) > 100:
        raise RuntimeError('The rewritten title must contain 1 to 100 characters.')
    os.replace(temporary, output)
    save(folder / 'ready.json', {'title': title, 'path': str(output), 'duration': rendered})
    progress(request, 95, 'Render and title verified.')
    return {'state': 'completed', 'render_verified': True, 'title': title}


def upload(task, request):
    folder = folder_for(task, task['video']['source_video_id'])
    ready = read(folder / 'ready.json')
    media = folder / 'render.mp4'
    verify(media)
    if ready['title'] != task['video']['title']:
        raise RuntimeError('Local title does not match the queued title.')
    progress(request, 15, 'Chrome is uploading the verified render to YouTube Studio.')
    result = browser('upload', path=str(media), title=ready['title'],
                     destination=task['channel']['destination'])
    if not result.get('publication_confirmed') or not re.fullmatch(r'[A-Za-z0-9_-]{11}', result.get('youtube_id', '')):
        raise RuntimeError('YouTube publication could not be confirmed.')
    save(folder / 'published.json', result)
    return {'state': 'completed', 'publication_confirmed': True, 'youtube_id': result['youtube_id']}


def main():
    request, result = map(Path, sys.argv[1:3])
    task = read(request)
    try:
        value = {'fetch': fetch, 'editor': edit, 'uploader': upload}[task['agent']](task, request)
    except Exception as error:
        print(type(error).__name__ + ': ' + str(error), flush=True)
        value = {'state': 'needs_attention' if task['agent'] == 'uploader' else 'failed',
                 'reason': 'Stage could not be verified. See the private VPS stage log.'}
    save(result, value)


if __name__ == '__main__':
    main()
