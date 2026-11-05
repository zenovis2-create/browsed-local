"""Check release source inventory; excludes known local-only files, never prints data."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent
LOCAL_NAMES = {
    "credentials.json", "config.json", "stream-state.json",
    "last-supervisor-error.json", "baseline-display.json", "display-target.json",
}
SOURCE_SUFFIXES = {".py", ".pyw", ".ps1", ".md", ".yml", ".yaml"}


def source_files():
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=False
    )
    if result.returncode == 0 and result.stdout:
        return [ROOT / name.decode("utf-8") for name in result.stdout.split(b"\0") if name]
    return [p for p in ROOT.rglob("*") if p.is_file() and not any(
        part in {".git", "__pycache__", "dist"} for part in p.relative_to(ROOT).parts
    ) and p.name not in LOCAL_NAMES]


class PackageHygieneTests(unittest.TestCase):
    def test_no_runtime_data_or_binaries_in_inventory(self):
        for path in source_files():
            self.assertNotIn(path.name, LOCAL_NAMES, path.name)
            self.assertFalse(path.name.startswith("credential-") and path.suffix == ".tmp", path.name)
            self.assertNotIn(path.suffix.lower(), {".exe", ".dll", ".msi", ".zip", ".lnk", ".png"}, path.name)
            self.assertNotIn("shared", path.relative_to(ROOT).parts, path.name)

    def test_no_machine_specific_source_or_private_keys(self):
        patterns = [
            re.compile(r"[A-Z]:\\Users\\[^\\\s]+\\", re.I),
            re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
            re.compile(r"(?:ghp|gho|github_pat)_[A-Za-z0-9_]{20,}"),
            re.compile(r"sk-[A-Za-z0-9]{32,}"),
        ]
        for path in source_files():
            if path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8-sig")
            for pattern in patterns:
                self.assertIsNone(pattern.search(text), f"Source hygiene violation: {path.name}")

    def test_gitignore_covers_private_state(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for name in LOCAL_NAMES:
            self.assertIn("**/" + name, text)
        self.assertIn("**/credential-*.tmp", text)


if __name__ == "__main__":
    unittest.main()
