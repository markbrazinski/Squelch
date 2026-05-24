#!/usr/bin/env python3
"""One-shot: write a GitHub PAT to Splunk storage/passwords.

Bundle 3 Sessions 25-26 setup. The `| squelch mode="tune"` pipeline
reads this secret via _fetch_github_token() (squelch_command.py).

Realm:    squelch_github
Username: default

Usage:
    ./scripts/setup_github_secret.py <ghp_TOKEN>

Reads SPLUNK_* from .env at the repo root, same as seed_notable.py.
"""

import os
import sys
from pathlib import Path

import splunklib.client as splunk_client


REALM = "squelch_github"
USERNAME = "default"


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip("'").strip('"'))


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: setup_github_secret.py <ghp_TOKEN>", file=sys.stderr)
        return 1
    pat = sys.argv[1].strip()
    if not (pat.startswith("ghp_") or pat.startswith("github_pat_")):
        print("warning: token doesn't look like a GitHub PAT "
              "(expected ghp_... or github_pat_...)", file=sys.stderr)

    repo_root = Path(__file__).resolve().parent.parent
    _load_env(repo_root / ".env")
    user = os.environ.get("SPLUNK_ADMIN_USER")
    pw = os.environ.get("SPLUNK_ADMIN_PASSWORD")
    host = os.environ.get("SPLUNK_HOST", "localhost")
    port = int(os.environ.get("SPLUNK_PORT", "8089"))
    if not (user and pw):
        print("error: SPLUNK_ADMIN_USER / SPLUNK_ADMIN_PASSWORD missing from .env",
              file=sys.stderr)
        return 1

    svc = splunk_client.connect(
        host=host, port=port, username=user, password=pw,
        scheme="https", verify=False, autologin=True,
    )

    # storage_passwords.create errors on duplicate — delete first if present.
    for cred in svc.storage_passwords:
        if cred.realm == REALM and cred.username == USERNAME:
            print(f"replacing existing secret at realm={REALM} username={USERNAME}")
            svc.storage_passwords.delete(USERNAME, realm=REALM)
            break

    svc.storage_passwords.create(pat, USERNAME, realm=REALM)
    print(f"OK: PAT stored at realm={REALM} username={USERNAME} (len={len(pat)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
