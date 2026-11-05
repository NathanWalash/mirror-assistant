import shutil

from mirror_voice.config import deep_merge, find_repo_root, load_config


def test_deep_merge_overrides_nested_keys_only():
    base = {"llm": {"port": 8080, "temperature": 0.8}, "persona": "a.md"}
    merged = deep_merge(base, {"llm": {"temperature": 1.2}})
    assert merged == {"llm": {"port": 8080, "temperature": 1.2}, "persona": "a.md"}
    assert base["llm"]["temperature"] == 0.8  # original untouched


def test_shipped_config_loads():
    cfg = load_config(find_repo_root())
    assert cfg.llm.base_url.startswith("http://127.0.0.1:")
    assert cfg.persona.name == "mirror.md"
    assert cfg.tts.voice.split("_")[0] in {"kokoro", "piper", "zipvoice"}


def test_personal_config_overrides_example(tmp_path):
    shutil.copy(find_repo_root() / "config.example.yaml", tmp_path / "config.example.yaml")
    (tmp_path / "config.yaml").write_text("llm:\n  temperature: 1.3\ntts:\n  voice: x_y\n")
    cfg = load_config(tmp_path)
    assert cfg.llm.temperature == 1.3
    assert cfg.tts.voice == "x_y"
    assert cfg.llm.port == 8080  # untouched keys still come from the example


def test_works_without_personal_config(tmp_path):
    shutil.copy(find_repo_root() / "config.example.yaml", tmp_path / "config.example.yaml")
    assert load_config(tmp_path).llm.port == 8080
