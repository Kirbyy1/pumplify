import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pumplify.config
from pumplify.config import load_dotenv, load_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _literal_env_args(call: ast.Call) -> list[str]:
    return [
        arg.value
        for arg in call.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    ]


def _first_literal_arg(call: ast.Call) -> str | None:
    if not call.args:
        return None

    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


def load_settings_env_keys() -> set[str]:
    source = Path(pumplify.config.__file__).read_text(encoding="utf-8")
    module = ast.parse(source)
    load_settings_node = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "load_settings"
    )

    keys = {"ENV_FILE_OVERRIDE"}
    for node in ast.walk(load_settings_node):
        if not isinstance(node, ast.Call):
            continue

        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "getenv"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
        ):
            key = _first_literal_arg(node)
            if key:
                keys.add(key)
            continue

        if isinstance(node.func, ast.Name) and node.func.id in {
            "env_bool",
            "env_int",
            "env_float",
        }:
            keys.update(_literal_env_args(node))

    return keys


def env_example_keys() -> set[str]:
    keys = set()
    for raw_line in (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        keys.add(line.split("=", 1)[0].strip())
    return keys


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

    def test_env_example_documents_supported_env_keys(self):
        self.assertEqual(env_example_keys(), load_settings_env_keys())


if __name__ == "__main__":
    unittest.main()
