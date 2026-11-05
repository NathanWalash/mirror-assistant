"""Mirror's talk loop: mic -> Moonshine -> llama.cpp (streamed) -> Piper -> speakers.

uv run mirror-talk              # live: just talk, Mirror answers when you pause
uv run mirror-talk --selftest   # no mic: Piper asks a question, the pipeline answers
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

from mirror_voice.config import Config, load_config
from mirror_voice.llm import Conversation, LLMClient, LLMUnavailable
from mirror_voice.persona import Persona
from mirror_voice.sentences import SentenceSplitter
from mirror_voice.tts import Voice


class Mirror:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.persona = Persona(cfg.persona)
        self.llm = LLMClient(cfg.llm)
        self.voice = Voice(cfg.tts)
        self.chat = Conversation(max_messages=cfg.llm.history_turns)

    def respond(self, user_text: str, heard_at: float, record_to: Path | None = None) -> None:
        """Stream the reply into a speaking thread, so speech starts after sentence one."""
        import sounddevice as sd  # imported lazily: needs PortAudio, not needed in tests

        messages = self.chat.build(self.persona.system_prompt())
        messages.append({"role": "user", "content": user_text})

        to_speak: queue.Queue[str | None] = queue.Queue()
        recorded: list[tuple[np.ndarray, int]] = []
        first_audio_at: list[float] = []

        def speaker() -> None:
            while (sentence := to_speak.get()) is not None:
                audio, rate = self.voice.synth(sentence)
                if not first_audio_at:
                    first_audio_at.append(time.time())
                if record_to:
                    recorded.append((audio, rate))
                else:
                    sd.play(audio, rate)
                    sd.wait()

        thread = threading.Thread(target=speaker, daemon=True)
        thread.start()

        splitter, reply = SentenceSplitter(), []
        print("Mirror: ", end="", flush=True)
        try:
            for delta in self.llm.stream(messages):
                for sentence in splitter.feed(delta):
                    print(sentence, end=" ", flush=True)
                    reply.append(sentence)
                    to_speak.put(sentence)
            if rest := splitter.flush():
                print(rest, end="", flush=True)
                reply.append(rest)
                to_speak.put(rest)
        finally:
            to_speak.put(None)
            thread.join()
        print()

        self.chat.add("user", user_text)
        self.chat.add("assistant", " ".join(reply))
        if first_audio_at:
            print(f"  [voice started {first_audio_at[0] - heard_at:.2f}s after you stopped]")
        if record_to and recorded:
            with wave.open(str(record_to), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(recorded[0][1])
                w.writeframes(np.concatenate([a for a, _ in recorded]).tobytes())


def stt_arch(name: str):
    from moonshine_voice import ModelArch

    try:
        return ModelArch[name.upper()]
    except KeyError:
        options = ", ".join(a.name.lower() for a in ModelArch)
        raise SystemExit(f"Unknown stt.model {name!r}. Options: {options}") from None


def selftest(mirror: Mirror) -> None:
    """End-to-end check without a mic: synthesise a question, transcribe it, answer it."""
    from moonshine_voice import get_model_for_language
    from moonshine_voice.transcriber import Transcriber

    question = "Morning Mirror. Should I bring a coat today?"
    audio, rate = mirror.voice.synth(question)
    pcm = audio.astype(np.float32) / 32768.0
    n = int(len(pcm) * 16000 / rate)
    pcm16k = np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm)

    model_path, arch = get_model_for_language("en", stt_arch(mirror.cfg.stt.model))
    stt = Transcriber(model_path, arch)
    started = time.time()
    lines = stt.transcribe_without_streaming(pcm16k.tolist(), 16000).lines
    heard = " ".join(line.text for line in lines).strip()
    print(f"Heard: {heard!r}  [speech-to-text {time.time() - started:.2f}s]")
    if not heard:
        raise SystemExit("Self-test failed: speech-to-text heard nothing.")

    out = mirror.cfg.root / "models" / "selftest_reply.wav"
    mirror.respond(heard, time.time(), record_to=out)
    print(f"Reply audio: {out}")


def live(mirror: Mirror) -> None:
    from moonshine_voice.mic_transcriber import MicTranscriber

    heard: queue.Queue[tuple[str, float]] = queue.Queue()
    mic = (
        MicTranscriber()
        .model_arch(stt_arch(mirror.cfg.stt.model))
        .on_text(lambda t: print(f"\r  (hearing) {t[-70:]:<70}", end="", flush=True))
        .on_line(lambda line: heard.put((line.text.strip(), time.time())))
    )
    print("Loading speech model...")
    mic.load()
    mic.start()
    print("Listening. Just talk; Mirror answers when you pause. Ctrl+C to quit.\n")
    try:
        while True:
            text, heard_at = heard.get()
            if len(text) < 2:
                continue
            print(f"\rYou: {text:<75}")
            mic.mute(True)  # don't transcribe Mirror's own voice from the speakers
            try:
                mirror.respond(text, heard_at)
            finally:
                time.sleep(0.3)
                while not heard.empty():
                    heard.get_nowait()
                mic.mute(False)
    except KeyboardInterrupt:
        print("\nTa-ra.")
    finally:
        mic.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Talk to Mirror.")
    parser.add_argument("--selftest", action="store_true", help="test without a microphone")
    args = parser.parse_args()

    cfg = load_config()
    mirror = Mirror(cfg)
    try:
        mirror.llm.check()
    except LLMUnavailable as e:
        sys.exit(str(e))
    (selftest if args.selftest else live)(mirror)


if __name__ == "__main__":
    main()
