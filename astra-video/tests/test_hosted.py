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
    for action in ['overview','jobs','channels','schedules','logs','analytics','settings']:
        assert 'error' not in json.loads(open_status(public,base+'api.php?action='+action,200))
    for action in ['queue','channel_save','channel_toggle','schedule_save','schedule_toggle','job_cancel','password_change','logout']:
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
    open_status(client,base+'api.php?action=logout',200,b'{}',{'Content-Type':'application/json','X-CSRF-Token':csrf})
    open_status(client,base+'api.php?action=overview',200)
    open_status(client,base+'api.php?action=queue',401,b'{}',{'Content-Type':'application/json','X-CSRF-Token':csrf})
    print('PASS: logout revokes writes while preserving public read access')


if __name__=='__main__':
    main()
