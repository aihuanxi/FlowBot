#!/usr/bin/env python3
"""FlowBot independent backend; Python 3.10+, no third-party packages."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import ssl
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def nonempty(value, name, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be a nonempty string (max {limit})")
    return value


class Store:
    def __init__(self, path, device_ids):
        self.path = str(path)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY, last_seen REAL, state TEXT);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, device_id TEXT NOT NULL, contact TEXT NOT NULL,
                    text TEXT NOT NULL, status TEXT NOT NULL, request_key TEXT UNIQUE NOT NULL,
                    detail TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, device_id TEXT NOT NULL, contact TEXT NOT NULL,
                    text TEXT NOT NULL, source TEXT NOT NULL, received REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS rules (
                    device_id TEXT NOT NULL, contact TEXT NOT NULL, trigger TEXT NOT NULL,
                    reply TEXT NOT NULL, PRIMARY KEY(device_id, contact));
            """)
            for device in device_ids:
                db.execute("INSERT OR IGNORE INTO devices(id) VALUES(?)", (device,))

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def task(db, task_id):
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def enqueue(self, db, device, contact, text, key):
        old = db.execute("SELECT * FROM tasks WHERE request_key=?", (key,)).fetchone()
        if old:
            if (old['device_id'], old['contact'], old['text']) != (device, contact, text):
                raise ValueError("request_id already used for a different message")
            return dict(old)
        task_id, now = str(uuid.uuid4()), time.time()
        db.execute("INSERT INTO tasks(id,device_id,contact,text,status,request_key,created,updated) "
                   "VALUES(?,?,?,?, 'queued',?,?,?)", (task_id, device, contact, text, key, now, now))
        return self.task(db, task_id)

    def poll(self, device, state):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE devices SET last_seen=?,state=? WHERE id=?",
                       (now, json.dumps(state, ensure_ascii=False), device))
            # A lost result must never silently become a second send.
            db.execute("UPDATE tasks SET status='unknown',detail='device result timeout',updated=? "
                       "WHERE device_id=? AND status='running' AND updated<?", (now, device, now-120))
            contacts = [r[0] for r in db.execute("SELECT contact FROM tasks WHERE device_id=? "
                       "UNION SELECT contact FROM rules WHERE device_id=?", (device, device))]
            task = None
            running = db.execute("SELECT 1 FROM tasks WHERE device_id=? AND status='running'", (device,)).fetchone()
            if state.get('ready') is True and not running:
                row = db.execute("SELECT id FROM tasks WHERE device_id=? AND status='queued' "
                                 "ORDER BY created LIMIT 1", (device,)).fetchone()
                if row:
                    db.execute("UPDATE tasks SET status='running',updated=? WHERE id=?", (now, row[0]))
                    task = self.task(db, row[0])
            return {'task': task, 'allowed_contacts': contacts}

    def result(self, device, body):
        task_id = nonempty(body.get('task_id'), 'task_id', 100)
        status = body.get('status')
        if status not in ('succeeded', 'failed', 'unknown'):
            raise ValueError('invalid result status')
        detail = str(body.get('detail', ''))[:2000]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self.task(db, task_id)
            if not old or old['device_id'] != device:
                raise ValueError('task does not belong to this device')
            if old['status'] not in ('running', 'unknown', status):
                raise ValueError('task is not running or result conflicts')
            db.execute("UPDATE tasks SET status=?,detail=?,updated=? WHERE id=?",
                       (status, detail, time.time(), task_id))
            return self.task(db, task_id)

    def receive(self, device, body):
        contact = nonempty(body.get('contact'), 'contact', 100)
        text = nonempty(body.get('text'), 'text', 4000)
        event_id = nonempty(body.get('event_id'), 'event_id', 200)
        source = body.get('source')
        if source != 'wecom_notification':
            raise ValueError('unsupported incoming source')
        # Namespace IDs by device so two phones cannot overwrite each other's events.
        key = hashlib.sha256((device + '\0' + event_id).encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            allowed = db.execute("SELECT 1 FROM tasks WHERE device_id=? AND contact=? "
                                 "UNION SELECT 1 FROM rules WHERE device_id=? AND contact=?",
                                 (device, contact, device, contact)).fetchone()
            if not allowed:
                raise ValueError('contact is not configured for this device')
            old = db.execute("SELECT * FROM events WHERE id=?", (key,)).fetchone()
            if old:
                if old['contact'] != contact or old['text'] != text:
                    raise ValueError('event_id payload conflict')
                return {'event_id': key, 'duplicate': True}
            db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",
                       (key, device, contact, text, source, time.time()))
            rule = db.execute("SELECT * FROM rules WHERE device_id=? AND contact=?", (device, contact)).fetchone()
            reply = None
            if rule and text == rule['trigger'] and text != rule['reply']:
                reply = self.enqueue(db, device, contact, rule['reply'], 'reply:' + key)
            return {'event_id': key, 'duplicate': False, 'reply_task': reply}


class Api(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # No message bodies or bearer tokens in logs.
        print(f"{self.client_address[0]} {self.command} {self.path.split('?')[0]} {args[1] if len(args)>1 else ''}", flush=True)

    def respond(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.handle_api()

    def do_POST(self):
        self.handle_api()

    def do_DELETE(self):
        self.handle_api()

    def handle_api(self):
        self.connection.settimeout(15)
        try:
            path = self.path.split('?')[0]
            if path == '/health' and self.command == 'GET':
                return self.respond(200, {'ok': True})
            token = self.headers.get('Authorization', '').removeprefix('Bearer ')
            config, store = self.server.config, self.server.store
            admin = hmac.compare_digest(token, config['admin_token'])
            device = next((k for k, v in config['devices'].items() if hmac.compare_digest(token, v)), None)
            if not (device if path.startswith('/device/') else admin):
                return self.respond(401, {'error': 'unauthorized'})
            body = {}
            if self.command in ('POST', 'DELETE'):
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384:
                    raise ValueError('JSON body required (max 16 KiB)')
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError('body must be an object')
            if self.command == 'POST' and path == '/device/poll':
                state = body.get('state', {})
                if not isinstance(state, dict):
                    raise ValueError('state must be an object')
                return self.respond(200, store.poll(device, state))
            if self.command == 'POST' and path == '/device/result':
                return self.respond(200, store.result(device, body))
            if self.command == 'POST' and path == '/device/incoming':
                return self.respond(200, store.receive(device, body))
            if admin and path in ('/messages', '/rules') and self.command in ('POST', 'DELETE'):
                device = body.get('device_id')
                if device not in config['devices']:
                    raise ValueError('unknown device_id')
                contact = nonempty(body.get('contact'), 'contact', 100)
                with store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    if path == '/messages' and self.command == 'POST':
                        text = nonempty(body.get('text'), 'text', 2000)
                        key = nonempty(body.get('request_id'), 'request_id', 100)
                        return self.respond(201, store.enqueue(db, device, contact, text, 'manual:' + key))
                    if path == '/rules':
                        if self.command == 'DELETE':
                            db.execute('DELETE FROM rules WHERE device_id=? AND contact=?', (device, contact))
                        else:
                            trigger = nonempty(body.get('trigger'), 'trigger', 4000)
                            reply = nonempty(body.get('reply'), 'reply', 2000)
                            if trigger == reply:
                                raise ValueError('trigger and reply must differ')
                            db.execute('INSERT OR REPLACE INTO rules VALUES(?,?,?,?)', (device, contact, trigger, reply))
                        return self.respond(200, {'ok': True})
            if admin and self.command == 'GET':
                with store.connect() as db:
                    if path.startswith('/tasks/'):
                        task = store.task(db, path[7:])
                        return self.respond(200 if task else 404, task or {'error': 'task not found'})
                    table = {'/tasks': 'tasks', '/events': 'events', '/devices': 'devices', '/rules': 'rules'}.get(path)
                    if table:
                        order = {'tasks': 'created DESC', 'events': 'received DESC', 'devices': 'id', 'rules': 'device_id,contact'}[table]
                        return self.respond(200, [dict(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY {order} LIMIT 100')])
            self.respond(404, {'error': 'not found'})
        except (ValueError, TypeError, KeyError) as e:
            self.respond(400, {'error': str(e)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception as e:
            print(f'API error: {type(e).__name__}', flush=True)
            self.respond(500, {'error': 'internal error'})


def load_config(path):
    config = json.loads(Path(path).read_text())
    nonempty(config.get('admin_token'), 'admin_token', 200)
    devices = config.get('devices')
    if not isinstance(devices, dict) or not 1 <= len(devices) <= 10:
        raise ValueError('configure 1 to 10 devices')
    tokens = [config['admin_token']]
    for device, token in devices.items():
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', device):
            raise ValueError('invalid device_id')
        nonempty(token, 'device token', 200)
        tokens.append(token)
    if any(len(t) < 32 for t in tokens) or len(set(tokens)) != len(tokens):
        raise ValueError('tokens must be distinct and at least 32 characters')
    return config


def make_server(host, port, db_path, config):
    server = ThreadingHTTPServer((host, port), Api)
    server.config = config
    server.store = Store(db_path, config['devices'])
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--db', default='flowbot.sqlite3')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--init', action='store_true')
    parser.add_argument('--device', action='append', default=[])
    parser.add_argument('--cert')
    parser.add_argument('--key')
    args = parser.parse_args()
    if args.init:
        config = {'admin_token': secrets.token_urlsafe(32), 'devices': {d: secrets.token_urlsafe(32) for d in args.device or ['oppo-test']}}
        if not 1 <= len(config['devices']) <= 10:
            parser.error('configure 1 to 10 devices')
        with open(args.config, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as f:
            json.dump(config, f, indent=2)
        load_config(args.config)
        print(f'Configuration created: {args.config}; tokens are stored only in this file')
        return
    os.umask(0o077)
    server = make_server(args.host, args.port, args.db, load_config(args.config))
    if bool(args.cert) != bool(args.key):
        parser.error('--cert and --key must be supplied together')
    if args.cert:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(args.cert, args.key)
        # Handshake in the request worker, so an idle TLS client cannot block accept().
        server.socket = tls.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    print(f'FlowBot listening at {args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
