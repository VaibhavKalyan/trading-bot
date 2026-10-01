"""
debug_auth.py — Run this to diagnose the 401 error.
It will check your keys, test the HMAC signing, and try the API.
"""
import os, hmac, hashlib, time, urllib.parse, requests
from dotenv import load_dotenv

load_dotenv()

API_KEY    = os.getenv("ROOSTOO_API_KEY", "")
SECRET_KEY = os.getenv("ROOSTOO_SECRET_KEY", "")
BASE_URL   = "https://mock-api.roostoo.com"

print("=" * 50)
print("STEP 1: Key check")
print("=" * 50)
print(f"API_KEY    : {repr(API_KEY[:10])}... (length={len(API_KEY)})")
print(f"SECRET_KEY : {repr(SECRET_KEY[:10])}... (length={len(SECRET_KEY)})")

if "your_testing" in API_KEY or len(API_KEY) < 10:
    print("\n❌ API_KEY is still a placeholder! Edit your .env file.")
    exit(1)
if "your_testing" in SECRET_KEY or len(SECRET_KEY) < 10:
    print("\n❌ SECRET_KEY is still a placeholder! Edit your .env file.")
    exit(1)
print("✅ Keys look non-empty.\n")

print("=" * 50)
print("STEP 2: HMAC signing test (matches Roostoo docs example)")
print("=" * 50)
# From Roostoo docs — known expected signature
test_params = "pair=BNB/USD&quantity=2000&side=BUY&timestamp=1580774512000&type=MARKET"
test_secret = "S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep"
expected_sig = "20b7fd5550b67b3bf0c1684ed0f04885261db8fdabd38611e9e6af23c19b7fff"
got_sig = hmac.new(test_secret.encode(), test_params.encode(), hashlib.sha256).hexdigest()
if got_sig == expected_sig:
    print("✅ HMAC signing logic is correct.\n")
else:
    print(f"❌ HMAC mismatch!\n  Expected: {expected_sig}\n  Got     : {got_sig}")
    exit(1)

print("=" * 50)
print("STEP 3: Live API call to /v3/balance")
print("=" * 50)
ts     = str(int(time.time() * 1000))
params = {"timestamp": ts}
sorted_p = sorted(params.items())
qs       = urllib.parse.urlencode(sorted_p)
sig      = hmac.new(SECRET_KEY.encode(), qs.encode(), hashlib.sha256).hexdigest()

print(f"Timestamp : {ts}")
print(f"Query str : {qs}")
print(f"Signature : {sig[:20]}...")

headers = {
    "RST-API-KEY":   API_KEY,
    "MSG-SIGNATURE": sig,
    "Content-Type":  "application/x-www-form-urlencoded",
}

try:
    resp = requests.get(f"{BASE_URL}/v3/balance", params=params, headers=headers, timeout=10)
    print(f"\nHTTP Status: {resp.status_code}")
    print(f"Response   : {resp.text[:300]}")
    if resp.status_code == 200:
        print("\n✅ SUCCESS! Auth is working.")
    elif resp.status_code == 401:
        print("\n❌ Still 401 — keys are wrong or not activated yet by Roostoo.")
        print("   → Try the competition keys instead.")
        print("   → Or contact Roostoo on WhatsApp — testing account may not be live yet.")
    else:
        print(f"\n⚠️  Unexpected status: {resp.status_code}")
except Exception as e:
    print(f"\n❌ Request failed: {e}")
