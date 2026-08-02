import json
import sys
import urllib.request

URL = "http://localhost:5000/api/kyc/verify"

payload = {
    "user_id": 1,
    "kyc_success": True,
    # tambahkan field lain sesuai kebutuhan backend Anda
    "app_ecosystem": "gojek,grab"
}

data = json.dumps(payload).encode("utf-8")

req = urllib.request.Request(
    URL,
    data=data,
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        print("STATUS:", resp.status)
        print("BODY:")
        print(body)
except Exception as e:
    print("REQUEST FAILED:", e)
    sys.exit(1)

