"""Owner-private Site calls. Pass credentials through hidden stdin, never arguments."""
import sys, json, termios, urllib.request, urllib.error
from pathlib import Path
if sys.stdin.isatty():
    settings=termios.tcgetattr(sys.stdin.fileno())
    settings[3] &= ~(termios.ECHO | termios.ICANON)
    termios.tcsetattr(sys.stdin.fileno(),termios.TCSANOW,settings)
print('Ready for private Site request JSON on stdin (hidden).',flush=True)
request=json.loads(sys.stdin.readline())
origin='https://vincent-ite-study-dashboard.grittypeach1026.chatgpt.site'
path=request.get('path','/api/agent')
if path not in ['/api/agent','/api/workflow','/api/study','/api/data']:
    raise ValueError('Unsupported Site path')
body=None
if path=='/api/agent':
    payload=request.get('payload')
    if request.get('payload_file'):
        payload=json.loads(Path(request['payload_file']).read_text())
    body=json.dumps({'action':request['action'],'payload':payload}).encode()
headers={'OAI-Sites-Authorization':'Bearer '+request['token'],'content-type':'application/json'}
req=urllib.request.Request(origin+path,data=body,headers=headers)
try:
    with urllib.request.urlopen(req,timeout=45) as response:
        result=json.load(response)
        if request.get('output_file'):
            Path(request['output_file']).write_text(json.dumps(result))
            print(json.dumps({'status':response.status,'output_saved':True}))
        else:
            print(json.dumps({'status':response.status,'result':result}))
except urllib.error.HTTPError as error:
    print(json.dumps({'status':error.code,'error':error.read().decode()}))
    sys.exit(1)
