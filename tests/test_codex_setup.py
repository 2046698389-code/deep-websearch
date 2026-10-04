import json

from scripts import install_codex, runtime_paths


def test_import_existing_search_fields_preserves_existing_and_excludes_tunnel(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / ".env.example").write_text("TIKHUB_API_KEY=\nTIKOMNI_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(install_codex, "ROOT", source_root)
    source = source_root / ".env"
    source.write_text("TikHub_key=fixture-new\nItkomni_key=fixture-omni\n"
                      "CONTROL_PLANE_API_KEY=do-not-import\nTIKHUB_API_KEY=fixture-replacement\n", encoding="utf-8")
    target = tmp_path / ".env"
    target.write_text("TIKHUB_API_KEY='fixture-keep'\n# user notes\n", encoding="utf-8")
    count, conflicts = install_codex.merge_credentials(source, target)
    assert count == 2 and conflicts == ["TIKHUB_API_KEY"]
    contents = target.read_text(encoding="utf-8")
    assert "fixture-keep" in contents and "user notes" in contents and "fixture-omni" in contents
    assert "do-not-import" not in contents and "fixture-replacement" not in contents


def test_windows_runtime_pointer_is_shared_with_non_packaged_shell(tmp_path):
    pointer = tmp_path / ".codex" / "deep-websearch-runtime.json"
    pointer.parent.mkdir()
    home = tmp_path / "app-redirect" / "runtime"
    pointer.write_text(json.dumps({"home": str(home)}), encoding="utf-8")
    assert runtime_paths.shared_home(platform="win32", environ={"LOCALAPPDATA": str(tmp_path / "other")},
                                     user_home=tmp_path) == home
