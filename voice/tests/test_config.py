import shutil

import pytest
from mirror_voice.config import (
    NightConfig,
    WidgetConfig,
    deep_merge,
    find_repo_root,
    load_config,
    merge_keyterms,
    parse_keyterms,
)


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


def test_widgets_section_loads_with_settings_and_overrides(tmp_path):
    shutil.copy(find_repo_root() / "config.example.yaml", tmp_path / "config.example.yaml")
    (tmp_path / "config.yaml").write_text("widgets:\n  weather:\n    latitude: 51.5\n")
    weather = load_config(tmp_path).widgets["weather"]
    assert weather.enabled is True
    assert weather.refresh_minutes == 15
    assert weather.settings["latitude"] == 51.5
    assert weather.settings["longitude"] == -1.5492  # still from the example
    assert "enabled" not in weather.settings


def test_widget_block_defaults():
    assert WidgetConfig.from_raw(None) == WidgetConfig(True, None, {})
    assert WidgetConfig.from_raw({"enabled": False, "refresh_minutes": 1}).refresh_minutes == 1.0


def test_night_dimming_defaults_and_overrides(tmp_path):
    shutil.copy(find_repo_root() / "config.example.yaml", tmp_path / "config.example.yaml")
    assert load_config(tmp_path).display.night == NightConfig("00:00", "06:30", 0.15)

    (tmp_path / "config.yaml").write_text(
        "display:\n  night:\n    start: 23:30\n    end: '7:00'\n    brightness: 0.3\n"
    )
    display = load_config(tmp_path).display
    assert display.night == NightConfig("23:30", "07:00", 0.3)  # unquoted 23:30 is fine too
    assert display.page_settings() == {
        "night": {"start": "23:30", "end": "07:00", "brightness": 0.3}
    }

    (tmp_path / "config.yaml").write_text("display:\n  night: false\n")
    display = load_config(tmp_path).display
    assert display.night is None and display.page_settings() == {"night": None}


def test_night_dimming_rejects_bad_times_and_ignores_no_ops():
    assert NightConfig.from_raw({"brightness": 1}) is None
    assert NightConfig.from_raw({"start": "05:00", "end": "05:00"}) is None
    assert NightConfig.from_raw({"brightness": -2}).brightness == 0.0
    for bad in ("25:00", "midnight", "6"):
        with pytest.raises(ValueError, match="06:30"):
            NightConfig.from_raw({"start": bad})


def personal(tmp_path, text: str):
    shutil.copy(find_repo_root() / "config.example.yaml", tmp_path / "config.example.yaml")
    (tmp_path / "config.yaml").write_text(text)
    return load_config(tmp_path)


def test_example_names_the_assistant_and_adds_no_personal_keyterms(tmp_path):
    shutil.copy(find_repo_root() / "config.example.yaml", tmp_path / "config.example.yaml")
    cfg = load_config(tmp_path)
    assert cfg.assistant.name == "Mirror"
    assert cfg.stt.keyterms == ()
    assert cfg.keyterms == ["Mirror"]


def test_personal_name_and_keyterms_reach_speech_to_text(tmp_path):
    cfg = personal(tmp_path, "assistant:\n  name: Robin\nstt:\n  keyterms: [Alex, Sam]\n")
    assert cfg.assistant.name == "Robin"
    assert cfg.keyterms == ["Robin", "Alex", "Sam"]
    assert cfg.stt.model == "small_streaming"  # rest of stt still from the example


def test_missing_assistant_section_defaults_to_mirror(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        "persona: p.md\nllm: {port: 1, model: m, context_size: 1, temperature: 1,"
        " max_tokens: 1, history_turns: 1}\nstt: {model: tiny}\ntts: {voice: v}\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.assistant.name == "Mirror"
    assert cfg.stt.keyterms == ()


def test_merge_keyterms_puts_name_first_and_drops_duplicates():
    terms = merge_keyterms("Robin", ["robin", " Alex ", "", "Sam", "alex"])
    assert terms == ["Robin", "Alex", "Sam"]


def test_parse_keyterms():
    assert parse_keyterms(None) == ()
    assert parse_keyterms([]) == ()
    assert parse_keyterms(["Alex", " Leeds ", ""]) == ("Alex", "Leeds")


@pytest.mark.parametrize("bad", ["Alex, Sam", ["Alex, Sam"], {"a": 1}])
def test_parse_keyterms_rejects_strings_and_commas(bad):
    with pytest.raises(ValueError):
        parse_keyterms(bad)


def test_name_with_comma_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        personal(tmp_path, "assistant:\n  name: Robin, the mirror\n")
