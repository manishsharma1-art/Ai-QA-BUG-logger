import urllib.request
import json

url = 'https://qa-bugbot-542857204182.asia-south1.run.app/webhook'
payload = {
    'type': 'MESSAGE',
    'message': {
        'name': 'spaces/AAA/messages/BBB',
        'text': '/status',
        'sender': {'name': 'users/123', 'displayName': 'E2E Tester'},
        'thread': {'name': 'spaces/AAA/threads/CCC'}
    },
    'space': {'name': 'spaces/AAA', 'type': 'ROOM'}
}
req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req) as response:
        data = response.read().decode('utf-8')
        print("Response:", data.encode('ascii', 'replace').decode('ascii'))
except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}: {e.read().decode('utf-8')}")
except Exception as e:
    print(f"Error: {e}")
