from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPERATOR_TEMPLATES = [
    PROJECT_ROOT / ".env_excuter_testnet.example",
    PROJECT_ROOT / ".env_excuter_mainnet.example",
]
SKILL_TEMPLATES = [
    PROJECT_ROOT / "skill/templates/env.testnet.example",
    PROJECT_ROOT / "skill/templates/env.mainnet.example",
]
if not SKILL_TEMPLATES[0].exists():
    SKILL_TEMPLATES = [
        PROJECT_ROOT.parent / "templates/env.testnet.example",
        PROJECT_ROOT.parent / "templates/env.mainnet.example",
    ]

ENV_TEMPLATE_PATHS: list[Path] = []
ENV_TEMPLATE_PATHS.extend(path for path in SKILL_TEMPLATES if path.exists())
ENV_TEMPLATE_PATHS.extend(path for path in OPERATOR_TEMPLATES if path.exists())

LEGACY_REPORT_KEYS = {
    "REPORT_REGISTRY_ADDRESS",
    "REPORT_STORAGE_PROVIDER",
    "REPORT_LOCAL_STORAGE_DIR",
    "PINATA_JWT",
    "IPFS_API_URL",
}


def _env_keys(path: Path) -> list[str]:
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z0-9_]+)=", line)
        if match:
            keys.append(match.group(1))
    return keys


def _env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


class EnvTemplateTest(unittest.TestCase):
    def test_ambiguous_generic_env_templates_are_absent(self) -> None:
        self.assertFalse((PROJECT_ROOT / ".env.example").exists())
        self.assertFalse((PROJECT_ROOT / "skill/templates/env.example").exists())
        self.assertFalse((PROJECT_ROOT.parent / "templates/env.example").exists())

    def test_env_templates_keep_same_supported_fields(self) -> None:
        key_sets = {str(path): set(_env_keys(path)) for path in ENV_TEMPLATE_PATHS}
        expected = key_sets[str(ENV_TEMPLATE_PATHS[0])]

        for path, keys in key_sets.items():
            self.assertSetEqual(keys, expected, path)

    def test_env_templates_do_not_repeat_keys(self) -> None:
        for path in ENV_TEMPLATE_PATHS:
            keys = _env_keys(path)
            repeated = sorted({key for key in keys if keys.count(key) > 1})
            self.assertEqual(repeated, [], str(path))

    def test_env_templates_exclude_legacy_reporting(self) -> None:
        for path in ENV_TEMPLATE_PATHS:
            self.assertTrue(LEGACY_REPORT_KEYS.isdisjoint(_env_keys(path)), str(path))

    def test_sqlite_database_is_separated_by_network(self) -> None:
        for path in ENV_TEMPLATE_PATHS:
            values = _env_values(path)
            expected = f"sqlite:///executor-{values['NETWORK']}.db"
            self.assertEqual(values["DATABASE_URL"], expected, str(path))
