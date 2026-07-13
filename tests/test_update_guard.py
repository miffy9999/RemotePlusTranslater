import hashlib
import json

import pytest

from update_guard import verify_update_tree


def make_update(tmp_path):
    package = tmp_path / "translator_app"
    package.mkdir()
    source = package / "__init__.py"
    source.write_text('__version__ = "test"\n', encoding="utf-8")
    relative = "translator_app/__init__.py"
    manifest = {
        "schema": 1,
        "files": {relative: hashlib.sha256(source.read_bytes()).hexdigest()},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return source


def test_complete_update_tree_is_accepted(tmp_path):
    make_update(tmp_path)
    assert verify_update_tree(tmp_path)["schema"] == 1


def test_unlisted_update_file_is_rejected(tmp_path):
    make_update(tmp_path)
    (tmp_path / "translator_app" / "extra.py").write_text("pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="extra=.*extra.py"):
        verify_update_tree(tmp_path)


def test_changed_update_file_is_rejected(tmp_path):
    source = make_update(tmp_path)
    source.write_text("changed = True\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_update_tree(tmp_path)


def test_parent_path_in_manifest_is_rejected(tmp_path):
    make_update(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = {"../outside.py": "0" * 64}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid update path"):
        verify_update_tree(tmp_path)
