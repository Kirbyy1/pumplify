import unittest

from pumplify.proxy import normalize_proxy_line


class ProxyTests(unittest.TestCase):
    def test_normalizes_host_port_proxy(self):
        self.assertEqual(
            normalize_proxy_line("127.0.0.1:8080"),
            "http://127.0.0.1:8080",
        )

    def test_normalizes_host_port_username_password_proxy(self):
        self.assertEqual(
            normalize_proxy_line("127.0.0.1:8080:user name:p@ss"),
            "http://user%20name:p%40ss@127.0.0.1:8080",
        )

    def test_keeps_full_proxy_url(self):
        self.assertEqual(
            normalize_proxy_line("http://user:pass@127.0.0.1:8080"),
            "http://user:pass@127.0.0.1:8080",
        )

    def test_ignores_blank_and_comment_lines(self):
        self.assertEqual(normalize_proxy_line(""), "")
        self.assertEqual(normalize_proxy_line("# comment"), "")


if __name__ == "__main__":
    unittest.main()
