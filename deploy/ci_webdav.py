"""Store a file in OpenCloud through its public address and read it back.

    python3 deploy/ci_webdav.py CLOUD_HOST STATE_DIR [CONNECT_IP]

CONNECT_IP sends this script, and only it, to that address for CLOUD_HOST
(like curl --resolve). Uses the app token the installer saved in STATE_DIR/secrets.json and the
installation's CA. A WebDAV PUT makes OpenCloud send the content to its
own public address (OC_URL/data) -- the step that fails when the pod
cannot reach that address or does not trust its certificate.
"""
import base64
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request


def main():
    host, state = sys.argv[1], sys.argv[2]
    if len(sys.argv) > 3:
        resolve = socket.getaddrinfo

        def pinned(name, *args, **kw):
            return resolve(sys.argv[3] if name == host else name, *args, **kw)
        socket.getaddrinfo = pinned
    with open(os.path.join(state, "secrets.json"), encoding="utf-8") as f:
        token = json.load(f).get("OPENCLOUD_APP_TOKEN", "")
    if not token:
        sys.exit("no OPENCLOUD_APP_TOKEN in secrets.json")
    ctx = ssl.create_default_context(cafile=os.path.join(state, "ca.crt"))
    auth = "Basic " + base64.b64encode(f"admin:{token}".encode()).decode()
    url = f"https://{host}/remote.php/dav/files/admin/locanoto-ci.txt"
    body = f"stored at {time.time()}\n".encode()

    def call(method, data=None):
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Authorization": auth})
        with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
            return r.status, r.read()

    for attempt in range(12):
        try:
            status, _ = call("PUT", body)
            break
        except urllib.error.HTTPError as e:
            # 5xx while OpenCloud's own public address is not served yet
            if e.code < 500 or attempt == 11:
                sys.exit(f"PUT {e.code}: {e.read()[:300]!r}")
            time.sleep(10)
    status, back = call("GET")
    if back != body:
        sys.exit(f"GET returned other content ({status})")
    print(f"OpenCloud: stored and read back via https://{host} (PUT {status})")


if __name__ == "__main__":
    main()
