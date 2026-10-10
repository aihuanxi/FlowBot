#!/usr/bin/env python3
"""Read the local configuration, then call the admin API without argv tokens."""
import argparse
import json
import ssl
from pathlib import Path
from urllib.request import Request, urlopen

p = argparse.ArgumentParser()
auth = p.add_mutually_exclusive_group(required=True)
auth.add_argument('--config', help='private backend config with admin_token')
auth.add_argument('--token-file', help='private token file, e.g. webhook inbox')
p.add_argument('--url', default='http://127.0.0.1:8787')
p.add_argument('--method', choices=['GET', 'POST', 'DELETE'], default='GET')
p.add_argument('--body-file')
p.add_argument('--ca', help='PEM certificate for an IP test server')
p.add_argument('path')
args = p.parse_args()
token = json.loads(Path(args.config).read_text())['admin_token'] if args.config else Path(args.token_file).read_text().strip()
body = Path(args.body_file).read_bytes() if args.body_file else None
request = Request(args.url.rstrip('/') + args.path, data=body, method=args.method,
                  headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
with urlopen(request, timeout=20, context=ssl.create_default_context(cafile=args.ca)) as response:
    print(json.dumps(json.load(response), ensure_ascii=False, indent=2))
