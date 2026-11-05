from mirror_voice.sentences import SentenceSplitter


def stream(text: str, chunk: int = 3) -> tuple[list[str], str | None]:
    """Feed `text` in small chunks, like tokens arriving from the model."""
    s = SentenceSplitter()
    out = []
    for i in range(0, len(text), chunk):
        out += s.feed(text[i : i + chunk])
    return out, s.flush()


def test_splits_on_sentence_ends_as_they_arrive():
    out, rest = stream("Bring a coat. It's grim out! Why ask me? ")
    assert out == ["Bring a coat.", "It's grim out!", "Why ask me?"]
    assert rest is None


def test_last_sentence_without_trailing_space_comes_from_flush():
    out, rest = stream("Morning. You look tired")
    assert out == ["Morning."]
    assert rest == "You look tired"


def test_does_not_split_decimals():
    out, rest = stream("It's 3.5 degrees. Coat.")
    assert out == ["It's 3.5 degrees."]
    assert rest == "Coat."


def test_keeps_ellipsis_and_closing_quotes_with_sentence():
    out, _ = stream('Well... fine. He said "no." Then left. ')
    assert out == ["Well...", "fine.", 'He said "no."', "Then left."]


def test_splits_on_newlines():
    out, rest = stream("First line\nSecond line")
    assert out == ["First line"]
    assert rest == "Second line"


def test_flush_on_empty_is_none():
    assert SentenceSplitter().flush() is None
