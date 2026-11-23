#!/usr/bin/env python3
"""Tests for diced.  python3 -m unittest discover -s daemon"""
import base64
import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import diced  # noqa: E402


class DicedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['DICE_USER'] = __import__('pwd').getpwuid(os.getuid()).pw_name
        cls.tmp = tempfile.mkdtemp()
        cls.web = os.path.join(cls.tmp, 'web')
        os.makedirs(cls.web)
        with open(os.path.join(cls.web, 'index.html'), 'w') as f:
            f.write('<!doctype html><html><head><title>t</title></head><body>hi</body></html>')
        with open(os.path.join(cls.web, 'a.js'), 'w') as f:
            f.write('var a = 1;')
        cls.settings = os.path.join(cls.tmp, 'etc', 'settings.json')
        cls.srv = diced.make_server(0, cls.web, cls.settings)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        home = os.path.expanduser('~')
        cls.play = os.path.join(home, 'dice-test-%d' % os.getpid())
        os.makedirs(cls.play, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        shutil.rmtree(cls.play, ignore_errors=True)

    def req(self, method, path, body=None, token=True, host=None, origin=None, raw=False):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        h = {'Host': host or '127.0.0.1:%d' % self.port}
        if token:
            h['X-Dice'] = diced.TOKEN
        if origin:
            h['Origin'] = origin
        data = body if (raw or body is None) else json.dumps(body)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = r.read()
        c.close()
        return r.status, out

    def j(self, *a, **k):
        code, out = self.req(*a, **k)
        return code, json.loads(out or b'{}')

    def test_desktop_page_gets_the_secret(self):
        code, out = self.req('GET', '/', token=False)
        self.assertEqual(code, 200)
        self.assertIn(b'window.DICE_SYS=', out)
        self.assertIn(diced.TOKEN.encode(), out)
        code, out = self.req('GET', '/a.js', token=False)
        self.assertEqual((code, out), (200, b'var a = 1;'))

    def test_outsiders_are_refused(self):
        self.assertEqual(self.req('GET', '/api/status', token=False)[0], 403)
        self.assertEqual(self.req('GET', '/api/status', host='evil.example:7070')[0], 403)
        self.assertEqual(self.req('GET', '/', token=False, host='rebind.example')[0], 403)
        self.assertEqual(self.req('POST', '/api/power', {'action': 'reboot'}, origin='https://evil.example')[0], 403)
        self.assertEqual(self.req('OPTIONS', '/api/status')[0], 403)
        self.assertEqual(self.req('GET', '/../../etc/passwd', token=False)[0], 404)

    def test_status(self):
        code, s = self.j('GET', '/api/status')
        self.assertEqual(code, 200)
        for k in ('version', 'host', 'user', 'uptime', 'mem', 'wifi', 'volume', 'brightness'):
            self.assertIn(k, s)

    def test_settings_never_keep_secrets(self):
        code, s = self.j('POST', '/api/settings', {'look': 'night', 'password': 'hunter2', 'wifi': {'password': 'x'}})
        self.assertEqual(code, 200)
        saved = json.load(open(self.settings))
        self.assertEqual(saved['look'], 'night')
        self.assertNotIn('password', saved)
        self.assertNotIn('wifi', saved)

    def test_files(self):
        rel = '~/' + os.path.basename(self.play)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'mkdir', 'path': rel + '/box'})[0], 200)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'text', 'path': rel + '/box/hi.txt', 'text': 'hello'})[0], 200)
        code, listing = self.j('GET', '/api/files?path=' + rel + '/box')
        self.assertEqual([i['name'] for i in listing['items']], ['hi.txt'])
        code, out = self.req('GET', '/api/file?path=' + rel + '/box/hi.txt')
        self.assertEqual(out, b'hello')
        code, out = self.req('POST', '/api/file?path=' + rel + '/box/raw.bin', body=b'\x00\x01', raw=True)
        self.assertEqual(code, 200)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'rename', 'path': rel + '/box/hi.txt', 'to': 'hey.txt'})[0], 200)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'rename', 'path': rel + '/box/hey.txt', 'to': '../x'})[0], 400)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'trash', 'path': rel + '/box/hey.txt'})[0], 200)
        self.assertFalse(os.path.exists(os.path.join(self.play, 'box', 'hey.txt')))
        # nothing outside home or plugged-in drives
        self.assertEqual(self.j('GET', '/api/files?path=/etc')[0], 400)
        self.assertEqual(self.req('GET', '/api/file?path=/etc/passwd')[0], 400)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'text', 'path': '/tmp/escape.txt', 'text': 'x'})[0], 400)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'trash', 'path': '~'})[0], 400)

    def test_only_web_addresses_open(self):
        code, r = self.j('POST', '/api/open', {'url': 'file:///etc/passwd'})
        self.assertFalse(r['ok'])

    def test_nm_fields(self):
        self.assertEqual(diced.split_nm(r'yes:My\:Net:80'), ['yes', 'My:Net', '80'])

    def ws_open(self, token):
        s = socket.create_connection(('127.0.0.1', self.port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall(('GET /api/term?token=%s&cols=80&rows=24 HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                   'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\nOrigin: http://127.0.0.1:%d\r\n\r\n' % (token, self.port, key, self.port)).encode())
        head = b''
        while b'\r\n\r\n' not in head:
            chunk = s.recv(1)
            if not chunk:
                break
            head += chunk
        return s, head, key

    def test_terminal(self):
        s, head, key = self.ws_open('nope')
        self.assertIn(b' 403 ', head.split(b'\r\n')[0])
        s.close()
        s, head, key = self.ws_open(diced.TOKEN)
        self.assertIn(b' 101 ', head.split(b'\r\n')[0])
        self.assertIn(diced.ws_accept(key).encode(), head)
        mask = os.urandom(4)
        msg = b'echo dice-$((6*7))\n'
        s.sendall(bytes([0x82, 0x80 | len(msg)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(msg)))
        got, end = b'', time.time() + 8
        s.settimeout(1)
        while b'dice-42' not in got and time.time() < end:
            try:
                data = s.recv(4096)
                if not data:
                    break
                got += data
            except socket.timeout:
                pass
        self.assertIn(b'dice-42', got)
        s.close()


if __name__ == '__main__':
    unittest.main()
