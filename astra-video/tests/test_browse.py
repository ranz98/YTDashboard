"""Read-only checks for hosted list filters and Sri Lanka date boundaries."""
import json
from datetime import datetime, timedelta, timezone
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://lightblue-mantis-659122.hostingersite.com/astra/api.php?'
SL = timezone(timedelta(hours=5, minutes=30))


def get(action, **query):
    with urllib.request.urlopen(BASE + urllib.parse.urlencode(dict(action=action, **query)), timeout=30) as response:
        return json.load(response)


def day(value):
    return datetime.fromisoformat(value.replace(' ', 'T')).replace(tzinfo=timezone.utc).astimezone(SL).date()


today = datetime.now(SL).date()
for action in ('video_list', 'task_list'):
    rows = get(action, sort='oldest')
    assert len(rows['items']) <= 100
    assert rows['total'] >= len(rows['items'])
    if len(rows['items']) > 1:
        assert get(action, sort='oldest', offset=1)['items'][0]['id'] == rows['items'][1]['id']
    for span in ('today', 'yesterday', 'week', 'month'):
        result = get(action, range=span)
        start = {'today': today, 'yesterday': today-timedelta(days=1),
                 'week': today-timedelta(days=today.weekday()), 'month': today.replace(day=1)}[span]
        end = today-timedelta(days=1) if span == 'yesterday' else today
        for row in result['items']:
            assert start <= day(row['downloaded_at'] if action == 'video_list' else row['activity_at']) <= end
    try:
        get(action, range='custom', **{'from': '2026-02-30', 'to': '2026-03-01'})
        raise AssertionError('Invalid date accepted')
    except urllib.error.HTTPError as error:
        assert error.code == 422
for stage, field in [('fetched', 'downloaded_at'), ('edited', 'edited_at'), ('uploaded', 'published_at')]:
    assert all(row[field] for row in get('video_list', stage=stage)['items'])
for stage in ('fetch', 'editor', 'uploader'):
    assert all(row['agent'] == stage for row in get('task_list', stage=stage)['items'])
assert all(row['state'] == 'failed' for row in get('task_list', state='failed')['items'])
print('PASS: pagination, stage/status filters, Sri Lanka ranges and invalid dates')
