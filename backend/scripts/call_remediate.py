import json
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BACKEND = "http://127.0.0.1:8000"
URL = BACKEND + "/violations/text/remediate"

payload = {"text_input": "Fuck you and your asshole friend", "mode": "mask"}
req = Request(URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
try:
    with urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8")
        print(body)
except HTTPError as e:
    print(f"HTTP {e.code}")
    try:
        print(e.read().decode())
    except Exception:
        pass
except Exception as e:
    print("Request failed:", e)
