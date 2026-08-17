import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from pumplify.wallet import is_auth_token_valid, load_saved_wallets, save_wallet


class WalletFileTests(unittest.TestCase):
    def test_missing_file_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            self.assertEqual(load_saved_wallets(path), [])

    def test_malformed_json_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wallets.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(load_saved_wallets(path), [])

    def test_loads_dict_with_wallets_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wallets.json"
            path.write_text(
                json.dumps({"wallets": [{"publicAddress": "a"}]}),
                encoding="utf-8",
            )
            self.assertEqual(load_saved_wallets(path), [{"publicAddress": "a"}])

    def test_loads_direct_list_and_skips_non_dict_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wallets.json"
            path.write_text(
                json.dumps([{"publicAddress": "a"}, "bad", 123, None]),
                encoding="utf-8",
            )
            self.assertEqual(load_saved_wallets(path), [{"publicAddress": "a"}])

    def test_auth_token_expiry_validation(self):
        now = datetime.now(UTC).timestamp()

        self.assertTrue(is_auth_token_valid({
            "authToken": "token",
            "authTokenExpiresAt": now + 60,
        }, now))
        self.assertFalse(is_auth_token_valid({
            "authToken": "token",
            "authTokenExpiresAt": now - 60,
        }, now))
        self.assertFalse(is_auth_token_valid({
            "authTokenExpiresAt": now + 60,
        }, now))
        self.assertFalse(is_auth_token_valid({
            "authToken": "token",
            "authTokenExpiresAt": "bad",
        }, now))

    def test_auth_token_created_at_fallback_validation(self):
        now = datetime.now(UTC).timestamp()

        self.assertTrue(is_auth_token_valid({
            "authToken": "token",
            "createdAt": datetime.now(UTC).isoformat(),
        }, now))
        self.assertFalse(is_auth_token_valid({
            "authToken": "token",
            "createdAt": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
        }, now))
        self.assertFalse(is_auth_token_valid({
            "authToken": "token",
            "createdAt": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        }, now))
        self.assertFalse(is_auth_token_valid({
            "authToken": "token",
        }, now))

    def test_concurrent_save_wallet_keeps_all_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wallets.json"
            settings = SimpleNamespace(
                wallet_output_path=path,
                target_wallet="target",
            )
            count = 100

            with ThreadPoolExecutor(max_workers=20) as pool:
                list(pool.map(
                    lambda i: save_wallet(
                        f"address-{i}",
                        f"private-{i}",
                        settings,
                        auth_token=f"token-{i}",
                    ),
                    range(count),
                ))

            data = json.loads(path.read_text(encoding="utf-8"))
            addresses = {entry["publicAddress"] for entry in data}

            self.assertEqual(len(data), count)
            self.assertEqual(addresses, {f"address-{i}" for i in range(count)})
            self.assertEqual({entry["status"] for entry in data}, {"completed"})


if __name__ == "__main__":
    unittest.main()
