"""Tests for dice-cloud-server (run: python3 -m unittest test_cloud_server, in this folder)."""
import http.client
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
loader = importlib.machinery.SourceFileLoader('dcs', os.path.join(HERE, 'dice-cloud-server'))
spec = importlib.util.spec_from_loader('dcs', loader)
dcs = importlib.util.module_from_spec(spec)
loader.exec_module(dcs)

BOX, PART = 'a' * 32, 'b' * 32
KEY = 'k3y-for-the-tests-0123456789'


class CloudServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.cfg = {'key': KEY, 'data': cls.dir, 'name': 'test-vm', 'quota_gb': 0.0001}  # about 100 KB
        cls.srv = dcs.make_server(cls.cfg, '127.0.0.1', 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def req(self, method, path, body=None, key=KEY):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        h = {'X-Dice-Key': key} if key else {}
        if body is not None:
            h['Content-Type'] = 'application/octet-stream'
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        return r.status, data, dict(r.getheaders())

    def test_needs_the_key(self):
        self.assertEqual(self.req('GET', '/api/status', key=None)[0], 401)
        self.assertEqual(self.req('GET', '/api/status', key='nope')[0], 401)
        code, body, _ = self.req('GET', '/api/status')
        self.assertEqual(code, 200)
        s = json.loads(body)
        self.assertEqual((s['kind'], s['name']), ('dice-cloud-pc', 'test-vm'))
        self.assertEqual(self.req('GET', '/', key=None)[0], 200)  # the plain page says nothing private

    def test_parts(self):
        part = os.urandom(64)
        self.assertEqual(self.req('PUT', '/dice/cloud/%s/files/%s' % (BOX, PART), part)[0], 200)
        code, body, _ = self.req('GET', '/dice/cloud/%s/files' % BOX)
        j = json.loads(body)
        self.assertEqual([p['p'] for p in j['parts']], [PART])
        self.assertEqual(j['used'], 64)
        self.assertEqual(self.req('GET', '/dice/cloud/%s/files/%s' % (BOX, PART))[1], part)
        self.assertEqual(self.req('DELETE', '/dice/cloud/%s/files/%s' % (BOX, PART))[0], 200)
        self.assertEqual(self.req('GET', '/dice/cloud/%s/files/%s' % (BOX, PART))[0], 404)
        # not a locked part, not a part name, too much
        self.assertEqual(self.req('PUT', '/dice/cloud/%s/files/%s' % (BOX, PART), b'short')[0], 400)
        self.assertEqual(self.req('PUT', '/dice/cloud/%s/files/../../etc' % BOX, part)[0], 404)
        self.assertEqual(self.req('PUT', '/dice/cloud/%s/files/%s' % (BOX, 'c' * 32), os.urandom(200 * 1024))[0], 507)

    def test_browsers_may_ask(self):
        code, _, h = self.req('OPTIONS', '/dice/cloud/%s/files/%s' % (BOX, PART), key=None)
        self.assertEqual(code, 204)
        self.assertIn('X-Dice-Key', h['Access-Control-Allow-Headers'])
        self.assertEqual(h['Access-Control-Allow-Origin'], '*')


if __name__ == '__main__':
    unittest.main()
