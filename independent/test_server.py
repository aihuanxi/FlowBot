import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from server import make_server, load_config


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
