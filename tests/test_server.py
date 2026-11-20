import os
import threading
import time
import http.client
import unittest
from pathlib import Path

import server
from http.server import ThreadingHTTPServer


class TestServerRange(unittest.TestCase):
    def setUp(self):
        # Ensure out directory and test file
        server.OUT.mkdir(exist_ok=True)
        self.fpath = server.OUT / "test_range.mp3"
        # Create a 1000-byte file
        data = bytes([i % 256 for i in range(1000)])
        self.fpath.write_bytes(data)
        # Start server on an ephemeral port
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()
        # Give it a moment to start
        time.sleep(0.05)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.t.join(timeout=1)
        try:
            self.fpath.unlink()
        except FileNotFoundError:
            pass

    def test_range_0_99(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        conn.request("GET", "/out/" + self.fpath.name, headers={"Range": "bytes=0-99"})
        resp = conn.getresponse()
        body = resp.read()
        self.assertEqual(resp.status, 206)
        self.assertIn("Content-Range", resp.headers)
        self.assertIn("Accept-Ranges", resp.headers)
        self.assertEqual(resp.headers.get("Accept-Ranges"), "bytes")
        self.assertEqual(len(body), 100)
        self.assertTrue(resp.headers.get("Content-Range").startswith("bytes 0-99/"))
        conn.close()

    def test_full_no_range(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        conn.request("GET", "/out/" + self.fpath.name)
        resp = conn.getresponse()
        body = resp.read()
        self.assertEqual(resp.status, 200)
        self.assertIn("Accept-Ranges", resp.headers)
        self.assertEqual(len(body), 1000)
        conn.close()


if __name__ == "__main__":
    unittest.main()
