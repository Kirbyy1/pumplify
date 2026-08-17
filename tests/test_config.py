import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pumplify.config import load_dotenv, load_settings


class ConfigTests(unittest.TestCase):
    def test_env_file_override_replaces_existing_environment_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "ENV_FILE_OVERRIDE=1\nTARGET_PROFILE=from-file\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"TARGET_PROFILE": "from-env"}, clear=False):
                load_dotenv(path)
                self.assertEqual(os.environ["TARGET_PROFILE"], "from-file")

    def test_target_profile_alias_is_preferred(self):
        with patch.dict(
            os.environ,
            {
                "TARGET_PROFILE": "manawinss",
                "PUMP_TARGET_WALLET": "old-wallet",
            },
            clear=False,
        ), patch("pumplify.config.load_dotenv"):
            self.assertEqual(load_settings().target_wallet, "manawinss")

    def test_profile_data_alias_enables_data_overrides(self):
        with patch.dict(os.environ, {"USE_PROFILE_DATA": "1"}, clear=False), patch(
            "pumplify.config.load_dotenv"
        ):
            self.assertTrue(load_settings().use_data_overrides)


if __name__ == "__main__":
    unittest.main()
