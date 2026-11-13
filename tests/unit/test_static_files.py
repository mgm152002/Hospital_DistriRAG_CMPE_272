"""Server secrets must not be reachable through frontend file serving."""
import tempfile
import unittest
from pathlib import Path


class StaticFilesTests(unittest.TestCase):
    def test_traversal_cannot_reach_server_configuration(self):
        from common.static import resolve_public_path
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "web" / "dist"
            root.mkdir(parents=True)
            with self.assertRaises(ValueError):
                resolve_public_path(root, "../../.env")

    def test_symlink_cannot_expose_server_secret(self):
        from common.static import resolve_public_path
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "dist"
            root.mkdir()
            (root / "leak").symlink_to(Path(folder) / ".env")
            with self.assertRaises(ValueError):
                resolve_public_path(root, "leak")

    def test_normal_asset_is_inside_public_directory(self):
        from common.static import resolve_public_path
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(resolve_public_path(root, "assets/app.js"), root.resolve() / "assets" / "app.js")


if __name__ == "__main__":
    unittest.main()


class CacheControlTests(unittest.TestCase):
    """A deploy must show up on the next page load: the HTML shell is revalidated, hashed assets are cached for good."""

    def test_the_html_shell_and_unhashed_files_are_always_revalidated(self):
        from common.static import cache_control
        for path in ("", "index.html", "assistant", "favicon.svg", "robots.txt"):
            self.assertEqual(cache_control(path), "no-cache", path)

    def test_hashed_build_assets_are_cached_for_a_year(self):
        from common.static import cache_control
        self.assertEqual(cache_control("assets/index-B938IXpj.js"), "public, max-age=31536000, immutable")
        self.assertEqual(cache_control("/assets/index-DqUB3HFG.css"), "public, max-age=31536000, immutable")
