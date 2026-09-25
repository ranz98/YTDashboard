"""Check upload reconciliation using authenticated, rolled-back fixtures."""
import http.cookiejar
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
from test_hosted import open_status

access=json.loads((Path(__file__).resolve().parents[1]/'data/admin-access.json').read_text())
base=access['url']
public=urllib.request.build_opener()
for action in ('upload_resolve','upload_resolution_checks'):
    open_status(public,base+'api.php?action='+action,401,b'{}',{'Content-Type':'application/json'})
client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
html=open_status(client,base+'login.php',200)
csrf=re.search(r'name="csrf" value="([^"]+)"',html).group(1)
html=open_status(client,base+'login.php',200,urllib.parse.urlencode(dict(csrf=csrf,email=access['email'],password=access['password'])).encode())
csrf=re.search(r'name="csrf-token" content="([^"]+)"',html).group(1)
open_status(client,base+'api.php?action=upload_resolve',403,b'{}',{'Content-Type':'application/json'})
result=json.loads(open_status(client,base+'api.php?action=upload_resolution_checks',200,b'{}',{'Content-Type':'application/json','X-CSRF-Token':csrf}))
assert result['ok'] and result['fixtures']=='rolled back'
print('PASS: public access and CSRF protection; '+str(len(result['checks']))+' upload resolution checks; all fixtures rolled back')
