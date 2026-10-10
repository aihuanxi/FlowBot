#!/usr/bin/env python3
"""Persist incoming webhooks before acknowledging; Agents read /events?after=<cursor>."""
import argparse
import hmac
import json
import os
from pathlib import Path
import sqlite3
import ssl
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class Receiver(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(self.command, self.path.split('?')[0], args[1], flush=True)

    def respond(self, code, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def do_POST(self):
        self.handle_event()

    def do_GET(self):
        self.handle_event()

    def handle_event(self):
        self.connection.settimeout(10)
        if not hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer ' + self.server.token).encode()):
            return self.respond(401, {'error': 'unauthorized'})
        try:
            path = urlsplit(self.path).path
            with sqlite3.connect(self.server.db, timeout=10) as db:
                db.row_factory = sqlite3.Row
                if self.command == 'POST' and path == '/webhook':
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 16384:
                        raise ValueError('JSON body required (max 16 KiB)')
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict) or body.get('type') != 'message.received':
                        raise ValueError('message.received event required')
                    for name, limit in [('event_id', 200), ('device_id', 64), ('contact', 100), ('text', 4000)]:
                        value = body.get(name)
                        if not isinstance(value, str) or not value.strip() or len(value) > limit:
                            raise ValueError('invalid ' + name)
                    if body.get('source') not in ('wecom_notification', 'wecom_accessibility') or type(body.get('received_at')) not in (float, int):
                        raise ValueError('source and received_at required')
                    raw = json.dumps(body, ensure_ascii=False, sort_keys=True)
                    db.execute('BEGIN IMMEDIATE')
                    old = db.execute('SELECT body FROM events WHERE id=?', (body['event_id'],)).fetchone()
                    if old and old['body'] != raw:
                        return self.respond(409, {'error': 'event_id payload conflict'})
                    if not old:
                        db.execute('INSERT INTO events(id,body,received) VALUES(?,?,?)', (body['event_id'], raw, time.time()))
                    # Commit before 2xx: a lost HTTP response can then be retried safely.
                    db.commit()
                    return self.respond(200, {'event_id': body['event_id'], 'duplicate': bool(old)})
                if self.command == 'GET' and path == '/events':
                    after = int(parse_qs(urlsplit(self.path).query).get('after', ['0'])[0])
                    if after < 0:
                        raise ValueError('after must be nonnegative')
                    rows = db.execute('SELECT * FROM events WHERE cursor>? ORDER BY cursor LIMIT 100', (after,)).fetchall()
                    events = [dict(json.loads(r['body']), cursor=r['cursor']) for r in rows]
                    return self.respond(200, {'events': events, 'next_cursor': rows[-1]['cursor'] if rows else after})
            self.respond(404, {'error': 'not found'})
        except (ValueError, TypeError) as e:
            self.respond(400, {'error': str(e)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception as e:
            print('Receiver error:', type(e).__name__, flush=True)
            self.respond(500, {'error': 'internal error'})


def make_receiver(host, port, db, token):
    if not isinstance(token, str) or not token.isascii() or len(token) < 32 or '\n' in token or '\r' in token:
        raise ValueError('private token of at least 32 characters required')
    server = ThreadingHTTPServer((host, port), Receiver)
    server.db, server.token = str(db), token
    with sqlite3.connect(server.db) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS events(cursor INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,body TEXT NOT NULL,received REAL NOT NULL)')
    return server


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', default='127.0.0.1'); p.add_argument('--port', type=int, default=8789)
    p.add_argument('--db', required=True); p.add_argument('--token-file', required=True)
    p.add_argument('--cert'); p.add_argument('--key')
    args = p.parse_args()
    if bool(args.cert) != bool(args.key):
        p.error('--cert and --key must be provided together')
    if args.host not in ('127.0.0.1', 'localhost', '::1') and not args.cert:
        p.error('non-loopback listener requires HTTPS')
    os.umask(0o077)
    server = make_receiver(args.host, args.port, args.db, Path(args.token_file).read_text().strip())
    if args.cert:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(args.cert, args.key)
        server.socket = tls.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
