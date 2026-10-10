import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from server import Api, make_server, load_config
from examples.webhook_receiver import make_receiver


class BackendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'test.sqlite3'
        self.config = {'admin_token': 'admin-' + 'a'*32, 'devices': {'phone1': 'one-' + 'b'*32, 'phone2': 'two-' + 'c'*32}}
        self.start()

    def start(self):
        self.server = make_server('127.0.0.1', 0, self.db, self.config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def tearDown(self):
        self.stop(); self.tmp.cleanup()

    def call(self, path, body=None, token=None, method=None):
        req = Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Authorization': 'Bearer ' + (token or self.config['admin_token']), 'Content-Type': 'application/json'},
                      method=method)
        try:
            with urlopen(req, timeout=5) as response: return response.status, json.load(response)
        except HTTPError as e: return e.code, json.load(e)

    def message(self, key='send1', device='phone1'):
        code, result = self.call('/messages', {'device_id': device, 'contact': '心向明月', 'text': '你好 2026-10-10', 'request_id': key})
        self.assertEqual(code, 201)
        return result

    def poll(self, device='phone1', ready=True):
        return self.call('/device/poll', {'state': {'ready': ready}}, self.config['devices'][device])[1]

    def test_auth_device_isolation_and_idempotent_send(self):
        self.assertEqual(self.call('/tasks', token='wrong')[0], 401)
        self.assertEqual(self.call('/tasks', token=self.config['devices']['phone1'])[0], 401)
        task = self.message()
        self.assertEqual(self.message()['id'], task['id'])
        self.assertEqual(self.call('/messages', {'device_id': 'phone1', 'contact': '其他人', 'text': '不同正文', 'request_id': 'send1'})[0], 400)
        self.assertIsNone(self.poll('phone2')['task'])
        self.assertIsNone(self.poll(ready=False)['task'])
        self.assertEqual(self.poll()['task']['id'], task['id'])
        self.assertIsNone(self.poll()['task'])
        body = {'task_id': task['id'], 'status': 'succeeded', 'detail': 'UI confirmed'}
        self.assertEqual(self.call('/device/result', body, self.config['devices']['phone2'])[0], 400)
        self.assertEqual(self.call('/device/result', body, self.config['devices']['phone1'])[0], 200)
        self.assertEqual(self.call('/device/result', body, self.config['devices']['phone1'])[0], 200)

    def test_real_interface_incoming_dedup_and_auto_reply(self):
        rule = {'device_id': 'phone1', 'contact': '心向明月', 'trigger': 'FlowBot测试', 'reply': '自动回复测试成功'}
        self.assertEqual(self.call('/rules', rule)[0], 200)
        event = {'event_id': 'notification-1', 'contact': '心向明月', 'text': 'FlowBot测试', 'source': 'wecom_notification'}
        code, result = self.call('/device/incoming', event, self.config['devices']['phone1'])
        self.assertEqual(code, 200); self.assertIsNotNone(result['reply_task'])
        self.assertTrue(self.call('/device/incoming', event, self.config['devices']['phone1'])[1]['duplicate'])
        self.assertEqual(len(self.call('/tasks')[1]), 1)
        event.update(event_id='notification-2', text='自动回复测试成功')
        self.assertIsNone(self.call('/device/incoming', event, self.config['devices']['phone1'])[1]['reply_task'])
        event.update(event_id='notification-3', contact='未授权联系人')
        self.assertEqual(self.call('/device/incoming', event, self.config['devices']['phone1'])[0], 400)
        self.assertEqual(len(self.call('/events')[1]), 2)

    def test_restart_preserves_queue_and_timeout_never_resends(self):
        first = self.message()
        self.poll()
        queued = self.message('send2')
        with self.server.store.connect() as db:
            db.execute('UPDATE tasks SET updated=? WHERE id=?', (time.time()-121, first['id']))
        self.stop(); self.start()
        self.assertEqual(self.poll()['task']['id'], queued['id'])
        self.assertEqual(self.call('/tasks/'+first['id'])[1]['status'], 'unknown')
        self.assertIsNone(self.poll()['task'])
        # A delayed real result may resolve an unknown task without causing another send.
        result = {'task_id': first['id'], 'status': 'succeeded', 'detail': 'delayed callback'}
        self.assertEqual(self.call('/device/result', result, self.config['devices']['phone1'])[0], 200)

    def test_parallel_polls_claim_only_one_task(self):
        self.message(); self.message('send2')
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: self.poll()['task'], range(5)))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_send_and_reply_committed_before_http_acknowledgment(self):
        observed = []
        class CheckCommitted(Api):
            def respond(handler, status, body):
                if status == 201:
                    with handler.server.store.connect() as db:
                        observed.append(handler.server.store.task(db, body['id']) is not None)
                super().respond(status, body)
        self.server.RequestHandlerClass = CheckCommitted
        self.message()
        self.subscribe()
        event = self.incoming()[1]
        self.call('/events/'+event['event_id']+'/reply', {'text': '已收到'})
        self.assertEqual(observed, [True, True])

    def subscribe(self):
        self.assertEqual(self.call('/subscriptions', {'device_id': 'phone1', 'contacts': ['心向明月']})[0], 200)

    def incoming(self, event_id='n1', source='wecom_notification', contact='心向明月'):
        return self.call('/device/incoming', {'event_id': event_id, 'contact': contact, 'text': '一个真实问题',
                         'source': source}, self.config['devices']['phone1'])

    def test_independent_subscription_cursor_and_reply(self):
        self.subscribe()
        self.assertEqual(self.poll()['allowed_contacts'], ['心向明月'])
        code, first = self.incoming(source='wecom_accessibility')
        self.assertEqual(code, 200)
        self.incoming('n2')
        page = self.call('/events?after=0&device_id=phone1&limit=1')[1]
        self.assertEqual(len(page['events']), 1)
        next_page = self.call('/events?after='+str(page['next_cursor']))[1]
        self.assertEqual(len(next_page['events']), 1)
        path = '/events/'+first['event_id']+'/reply'
        task = self.call(path, {'text': 'Agent 理解后的回复'})[1]
        self.assertEqual(task['contact'], '心向明月')
        self.assertEqual(self.call(path, {'text': 'Agent 理解后的回复'})[1]['id'], task['id'])
        self.assertEqual(self.call(path, {'text': '不同回复'})[0], 400)
        self.assertEqual(self.call('/events/missing/reply', {'text': '回复'})[0], 404)
        self.assertEqual(self.call('/events?after=-1')[0], 400)
        self.assertEqual(self.call('/subscriptions', {'device_id': 'phone1', 'contacts': []})[0], 200)
        self.assertEqual(self.incoming('blocked')[0], 400)
        self.assertEqual(self.call('/subscriptions', {'device_id': 'phone1', 'listen_all': True})[0], 200)
        self.assertTrue(self.poll()['listen_all'])
        self.assertEqual(self.incoming('new-contact', contact='新联系人')[0], 200)

    def wait_delivery(self, status):
        end = time.monotonic()+6
        while time.monotonic()<end:
            rows = self.call('/webhook/deliveries')[1]
            if rows and rows[0]['status']==status:
                return rows[0]
            time.sleep(.05)
        self.fail('webhook did not reach '+status)

    def test_webhook_real_http_retry_restart_and_receiver_dedup(self):
        receiver_db = Path(self.tmp.name)/'receiver.sqlite3'
        receiver = make_receiver('127.0.0.1', 0, receiver_db, 'r'*32)
        thread = threading.Thread(target=receiver.serve_forever, daemon=True); thread.start()
        url = f'http://127.0.0.1:{receiver.server_port}'
        try:
            self.subscribe()
            settings = {'url': url+'/webhook', 'token': 'wrong-'+'w'*32}
            self.assertEqual(self.call('/webhook', settings)[0], 200)
            first = self.incoming()[1]
            failed = self.wait_delivery('retry')
            self.assertEqual(failed['last_status'], 401)
            self.stop(); self.start()
            settings['token']='r'*32
            self.call('/webhook', settings)
            delivered = self.wait_delivery('delivered')
            self.assertGreaterEqual(delivered['attempts'], 2)
            self.assertEqual(delivered['event_id'], first['event_id'])
            self.assertNotIn('token', self.call('/webhook')[1])
            self.assertIs(self.call('/webhook')[1]['enabled'], True)
            req = Request(url+'/events?after=0', headers={'Authorization':'Bearer '+'r'*32})
            with urlopen(req) as response: inbox=json.load(response)
            self.assertEqual(len(inbox['events']), 1)
            event = dict(inbox['events'][0]); event.pop('cursor')
            self.assertEqual(event['event_id'], first['event_id']); self.assertEqual(event['text'], '一个真实问题')
            req = Request(url+'/webhook', data=json.dumps(event).encode(), headers={'Authorization':'Bearer '+'r'*32})
            with urlopen(req) as response: self.assertTrue(json.load(response)['duplicate'])
            changed = dict(event, text='conflicting payload')
            with self.assertRaises(HTTPError) as conflict:
                urlopen(Request(url+'/webhook', data=json.dumps(changed).encode(), headers={'Authorization':'Bearer '+'r'*32}))
            self.assertEqual(conflict.exception.code, 409); conflict.exception.close()
            receiver.shutdown(); receiver.server_close(); thread.join()
            receiver = make_receiver('127.0.0.1', 0, receiver_db, 'r'*32)
            thread = threading.Thread(target=receiver.serve_forever, daemon=True); thread.start()
            url = f'http://127.0.0.1:{receiver.server_port}'
            with urlopen(Request(url+'/events?after=0', headers={'Authorization':'Bearer '+'r'*32})) as response:
                restored = json.load(response)
            self.assertEqual(restored, inbox)
            with urlopen(Request(url+'/events?after='+str(restored['next_cursor']), headers={'Authorization':'Bearer '+'r'*32})) as response:
                self.assertEqual(json.load(response)['events'], [])
            self.incoming()
            self.assertEqual(len(self.call('/webhook/deliveries')[1]), 1)
            self.stop(); self.start()
            self.assertEqual(self.call('/webhook/deliveries')[1][0]['status'], 'delivered')
            self.assertEqual(self.poll()['allowed_contacts'], ['心向明月'])
        finally:
            receiver.shutdown(); receiver.server_close(); thread.join()

    def test_webhook_configuration_and_no_history_replay(self):
        self.subscribe(); self.incoming()
        settings={'url':'http://127.0.0.1:9/webhook','token':'r'*32}
        for bad in [dict(settings,url='http://remote.example/webhook'),dict(settings,token='short'),
                    dict(settings,url='https://user:pass@example.com/'),dict(settings,ca_pem='bad PEM')]:
            self.assertEqual(self.call('/webhook',bad)[0],400)
        self.call('/webhook',settings)
        self.assertEqual(self.call('/webhook/deliveries')[1],[])
        self.assertEqual(self.call('/webhook',settings,token=self.config['devices']['phone1'])[0],401)

    def test_webhook_redirect_does_not_forward_credentials(self):
        hits = []
        class Redirect(BaseHTTPRequestHandler):
            def do_POST(handler):
                hits.append(handler.path)
                handler.send_response(302); handler.send_header('Location', '/forwarded'); handler.end_headers()
            def do_GET(handler):
                hits.append(handler.path); handler.send_response(200); handler.end_headers()
            def log_message(handler, *args): pass
        remote = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
        worker = threading.Thread(target=remote.serve_forever, daemon=True); worker.start()
        try:
            self.subscribe()
            self.call('/webhook', {'url': f'http://127.0.0.1:{remote.server_port}/webhook', 'token': 'r'*32})
            self.incoming()
            self.assertEqual(self.wait_delivery('retry')['last_status'], 302)
            self.assertEqual(hits, ['/webhook'])
        finally:
            remote.shutdown(); remote.server_close(); worker.join()

    def test_configuration_limits_and_distinct_device_credentials(self):
        path = Path(self.tmp.name) / 'config.json'
        config = {'admin_token': 'a'*32, 'devices': {f'phone{i}': f'{i:032d}' for i in range(10)}}
        path.write_text(json.dumps(config))
        self.assertEqual(len(load_config(path)['devices']), 10)
        for devices in ({}, {f'phone{i}': f'{i:032d}' for i in range(11)},
                        {'phone1': 'a'*32}, {'phone1': 'short'}, {'invalid id': 'b'*32}):
            path.write_text(json.dumps(dict(config, devices=devices)))
            with self.assertRaises(ValueError): load_config(path)


if __name__ == '__main__':
    unittest.main()
