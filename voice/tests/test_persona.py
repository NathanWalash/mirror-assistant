import pytest
from mirror_voice.persona import Persona


def test_strips_human_comments(tmp_path):
    p = tmp_path / "mirror.md"
    p.write_text("<!-- note to flatmate -->\nYou are Mirror.\n<!-- another\nnote -->\nBe dry.")
    assert Persona(p).system_prompt() == "You are Mirror.\n\nBe dry."


def test_reads_fresh_every_time(tmp_path):
    p = tmp_path / "mirror.md"
    persona = Persona(p)
    p.write_text("Version one.")
    assert persona.system_prompt() == "Version one."
    p.write_text("Version two.")
    assert persona.system_prompt() == "Version two."


def test_falls_back_to_example_template(tmp_path):
    (tmp_path / "mirror.example.md").write_text("Template persona.")
    assert Persona(tmp_path / "mirror.md").system_prompt() == "Template persona."


def test_private_copy_wins_over_template(tmp_path):
    (tmp_path / "mirror.example.md").write_text("Template persona.")
    (tmp_path / "mirror.md").write_text("Private persona.")
    assert Persona(tmp_path / "mirror.md").system_prompt() == "Private persona."


def test_missing_persona_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="mirror.md"):
        Persona(tmp_path / "mirror.md").system_prompt()


def test_shipped_template_is_valid():
    from mirror_voice.config import find_repo_root

    root = find_repo_root()
    prompt = Persona(root / "personality/personas/mirror.example.md").system_prompt()
    assert "Mirror" in prompt
    assert "<!--" not in prompt
