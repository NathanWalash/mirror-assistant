from mirror_voice.llm import Conversation, parse_sse_line


def test_parse_sse_line_extracts_delta():
    line = 'data: {"choices":[{"delta":{"content":"Ey up"}}]}'
    assert parse_sse_line(line) == "Ey up"


def test_parse_sse_line_ignores_noise():
    assert parse_sse_line("data: [DONE]") == ""
    assert parse_sse_line(": keep-alive") == ""
    assert parse_sse_line('data: {"choices":[{"delta":{}}]}') == ""
    assert parse_sse_line('data: {"choices":[]}') == ""


def test_conversation_keeps_only_recent_messages():
    chat = Conversation(max_messages=4)
    for i in range(6):
        chat.add("user", f"m{i}")
    assert [m["content"] for m in chat.messages] == ["m2", "m3", "m4", "m5"]


def test_conversation_puts_system_prompt_first():
    chat = Conversation(max_messages=4)
    chat.add("user", "hi")
    built = chat.build("You are Mirror.")
    assert built[0] == {"role": "system", "content": "You are Mirror."}
    assert built[1] == {"role": "user", "content": "hi"}
