"""Run dependency-free checks when the container test environment is unavailable.

This deliberately does not stand in for lint, pytest, integration, browser or provider eval checks.
"""
import importlib
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULES = ("test_ids", "test_snippet", "test_abbreviations", "test_architecture", "test_docs")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.unit.test_safety_regressions")
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName("tests.unit.test_openrouter_settings"))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName("tests.unit.test_static_files"))
    for name in MODULES:
        module = importlib.import_module(f"tests.unit.{name}")
        for attribute in sorted(vars(module)):
            test = getattr(module, attribute)
            if attribute.startswith("test_") and callable(test):
                suite.addTest(unittest.FunctionTestCase(test, description=f"{name}.{attribute}"))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
