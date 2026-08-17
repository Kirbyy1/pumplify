import tempfile
import unittest
from pathlib import Path

from pumplify.config import Settings
from pumplify.validation import validate_settings


class ValidationTests(unittest.TestCase):
    def test_rejects_empty_proxy_test_url_when_proxy_testing_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                pfp_path=root / "pfp.jpg",
                proxy_file=root / "proxies.txt",
                proxy_test_url="",
            )
            settings.pfp_path.write_text("image", encoding="utf-8")
            settings.proxy_file.write_text("proxy", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "PROXY_TEST_URL"):
                validate_settings(settings)

    def test_rejects_non_positive_proxy_test_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                pfp_path=root / "pfp.jpg",
                proxy_file=root / "proxies.txt",
                proxy_test_timeout=0,
            )
            settings.pfp_path.write_text("image", encoding="utf-8")
            settings.proxy_file.write_text("proxy", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "PROXY_TEST_TIMEOUT"):
                validate_settings(settings)

    def test_rejects_run_log_path_that_is_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                pfp_path=root / "pfp.jpg",
                proxy_file=root / "proxies.txt",
                run_log_dir=root / "runs",
            )
            settings.pfp_path.write_text("image", encoding="utf-8")
            settings.proxy_file.write_text("proxy", encoding="utf-8")
            settings.run_log_dir.write_text("not a directory", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "RUN_LOG_DIR"):
                validate_settings(settings)


if __name__ == "__main__":
    unittest.main()
