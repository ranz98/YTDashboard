"""Authenticated read checks and rejected-write checks against the hosted app."""
import http.cookiejar
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
access=json.loads((ROOT/'data/admin-access.json').read_text())
base=access['url']


def open_status(client,url,expected,body=None,headers=None):
    request=urllib.request.Request(url,data=body,headers=headers or {})
    try:
        response=client.open(request,timeout=30)
    except urllib.error.HTTPError as error:
        response=error
    assert response.code==expected,(url,response.code,expected)
    return response.read().decode()


def main():
    public=urllib.request.build_opener()
    assert json.loads(open_status(public,base+'api.php?action=health',200))['installed']
    html=open_status(public,base+'index.php',200)
    assert 'content="public"' in html
    for action in ['overview','jobs','channels','schedules','logs','analytics','settings','operations','errors','video_checks']:
        assert 'error' not in json.loads(open_status(public,base+'api.php?action='+action,200))
    for action in ['queue','channel_save','channel_toggle','schedule_save','schedule_toggle','job_cancel','password_change','logout','pipeline_control','agent_control','agent_schedule','agent_run','task_skip','task_retry','operations_migrate','worker_register','queue_checks']:
        open_status(public,base+'api.php?action='+action,401,b'{}',{'Content-Type':'application/json'})
    for path in ['private/config.php','private/bootstrap.php','private/schema.sql','setup.php']:
        open_status(public,base+path,403)
    print('PASS: public dashboard/read APIs, blocked public writes, installer lock and private files')
    client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    html=open_status(client,base+'login.php',200)
    csrf=re.search(r'name="csrf" value="([^"]+)"',html).group(1)
    html=open_status(client,base+'login.php',200,urllib.parse.urlencode(dict(csrf=csrf,email=access['email'],password=access['password'])).encode())
    csrf=re.search(r'name="csrf-token" content="([^"]+)"',html).group(1)
    for action in ['overview','jobs','channels','schedules','logs','analytics','settings']:
        result=json.loads(open_status(client,base+'api.php?action='+action,200))
        assert 'error' not in result
        print('PASS:',action)
    open_status(client,base+'api.php?action=queue',403,b'{"channel_id":0}',{'Content-Type':'application/json'})
    open_status(client,base+'api.php?action=queue',422,b'{"channel_id":0}',{'Content-Type':'application/json','X-CSRF-Token':csrf})
    open_status(client,base+'api.php?action=channel_save',422,b'{"name":"Invalid","handle":"not-a-handle"}',{'Content-Type':'application/json','X-CSRF-Token':csrf})
    open_status(client,base+'api.php?action=queue',405)
    print('PASS: CSRF, invalid job/channel rejection, method enforcement')
    response=json.loads(open_status(client,base+'api.php?action=queue_checks',200,b'{}',{'Content-Type':'application/json','X-CSRF-Token':csrf}))
    assert response['ok'] and response['fixtures']=='rolled back'
    print('PASS:',len(response['checks']),'transactional queue checks')
    ops=json.loads(open_status(public,base+'api.php?action=operations',200))
    assert ops['timezone']=='Asia/Colombo' and ops['fetch_limit']==5
    assert len(next(a for a in ops['agents'] if a['name']=='fetch')['slots'])==3
    assert len(next(a for a in ops['agents'] if a['name']=='uploader')['slots'])==3
    assert all('lease_hash' not in task for task in ops['tasks'])
    print('PASS: Sri Lanka display, latest-five policy, daily slots and lease privacy')
    headers={'Content-Type':'application/json','X-CSRF-Token':csrf}
    invalid=json.dumps({'agent':'fetch','slots':['08:00','08:00','08:00']}).encode()
    open_status(client,base+'api.php?action=agent_schedule',422,invalid,headers)
    if not ops['online'] and ops['paused']:
        try:
            open_status(client,base+'api.php?action=pipeline_control',200,b'{"command":"start"}',headers)
            assert not json.loads(open_status(public,base+'api.php?action=operations',200))['paused']
        finally:
            open_status(client,base+'api.php?action=pipeline_control',200,b'{"command":"stop"}',headers)
        assert json.loads(open_status(public,base+'api.php?action=operations',200))['paused']
        print('PASS: start/stop persist and restore the paused state')
    open_status(public,base+'worker.php',401,b'{"action":"claim"}',{'Content-Type':'application/json'})
    open_status(client,base+'api.php?action=logout',200,b'{}',{'Content-Type':'application/json','X-CSRF-Token':csrf})
    open_status(client,base+'api.php?action=overview',200)
    open_status(client,base+'api.php?action=queue',401,b'{}',{'Content-Type':'application/json','X-CSRF-Token':csrf})
    print('PASS: logout revokes writes while preserving public read access')


if __name__=='__main__':
    main()
