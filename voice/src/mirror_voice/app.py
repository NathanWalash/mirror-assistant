"""The talk loop: mic -> Moonshine -> llama.cpp (streamed) -> Kokoro/Piper -> speakers.

uv run mirror-talk              # live: just talk, the assistant answers when you pause
uv run mirror-talk --selftest   # no mic: a synthetic voice asks, the pipeline answers
uv run mirror-talk --bench      # time every stage (also: --bench tts, --bench stt)
uv run mirror-talk --voices     # list every voice you can put in your config.yaml
uv run mirror-talk --say "Ey up" [--voice kokoro_bm_lewis]   # hear a voice

The assistant's name ("Mirror" unless your config.yaml says otherwise) is assistant.name.

While live, the display (glowing orb, subtitles, widgets) is served at http://127.0.0.1:8765/.
To see the display and widgets without the voice loop: uv run mirror-hub
"""

from __future__ import annotations

import argparse
import logging
import queue
import sys
import threading
import time
import wave
import webbrowser
from dataclasses import replace
from pathlib import Path

import numpy as np

from mirror_voice import bench
from mirror_voice.config import Config, load_config
from mirror_voice.display_server import Broadcaster, DisplayServer, loudness
from mirror_voice.hub import Hub
from mirror_voice.llm import Conversation, LLMClient, LLMUnavailable
from mirror_voice.metrics import ReplyTimings
from mirror_voice.persona import Persona
from mirror_voice.sentences import SentenceSplitter
from mirror_voice.stt import SpeechToText, apply_keyterms, stt_arch
from mirror_voice.tts import Voice, available_voices


class Mirror:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.name = cfg.assistant.name
        self.persona = Persona(cfg.persona)
        self.llm = LLMClient(cfg.llm)
        self.voice = Voice(cfg.tts)
        self.chat = Conversation(max_messages=cfg.llm.history_turns)
        # Publishing with no page open is a harmless no-op.
        self.display = Broadcaster(cfg.display.page_settings())

    def respond(
        self,
        user_text: str,
        heard_at: float,
        record_to: Path | None = None,
        play: bool = True,
    ) -> ReplyTimings:
        """Stream the reply into a speaking thread, so speech starts after sentence one.

        `record_to` saves the reply as a WAV instead of playing it; `play=False` just
        throws the audio away (for benchmarks). Returns how long each stage took.
        """
        import sounddevice as sd  # imported lazily: needs PortAudio, not needed in tests

        started = time.perf_counter()
        timings = ReplyTimings()
        play = play and record_to is None
        self.display.publish(state="thinking")
        messages = self.chat.build(self.persona.system_prompt())
        messages.append({"role": "user", "content": user_text})

        # Three stages run at once so nothing waits on anything else:
        #   this thread: LLM tokens -> sentences      -> to_speak
        #   synth:       sentences  -> audio chunks   -> to_play   (streamed, first chunk fast)
        #   player:      audio chunks -> speakers + orb + subtitles
        to_speak: queue.Queue[str | None] = queue.Queue()
        to_play: queue.Queue[tuple[str | None, np.ndarray, int] | None] = queue.Queue()
        recorded: list[tuple[np.ndarray, int]] = []
        first_audio_at: list[float] = []

        def synth() -> None:
            try:
                while (sentence := to_speak.get()) is not None:
                    began = time.perf_counter()
                    for i, (audio, rate) in enumerate(self.voice.stream(sentence)):
                        if not first_audio_at:
                            first_audio_at.append(time.time())
                            timings.first_audio = time.perf_counter() - started
                        timings.audio_seconds += len(audio) / rate
                        to_play.put((sentence if i == 0 else None, audio, rate))
                    timings.synth_seconds += time.perf_counter() - began
            finally:
                to_play.put(None)

        def player() -> None:
            out = None
            try:
                while (item := to_play.get()) is not None:
                    sentence, audio, rate = item
                    if sentence:
                        self.display.publish(state="speaking", say=sentence)
                    if record_to:
                        recorded.append((audio, rate))
                    if not play:
                        continue
                    if out is None or out.samplerate != rate:
                        if out is not None:
                            out.stop()
                            out.close()
                        out = sd.OutputStream(samplerate=rate, channels=1, dtype="int16")
                        out.start()
                    # Write in 50 ms slices: the blocking write paces playback in real
                    # time, so each loudness update lands as that slice is heard.
                    step = int(rate * 0.05)
                    for start in range(0, len(audio), step):
                        piece = audio[start : start + step]
                        self.display.publish(level=loudness(piece))
                        out.write(piece.reshape(-1, 1))
            finally:
                if out is not None:
                    out.stop()  # waits for the last audio to finish playing
                    out.close()

        threads = [
            threading.Thread(target=synth, daemon=True),
            threading.Thread(target=player, daemon=True),
        ]
        for thread in threads:
            thread.start()

        splitter, reply, chunks = SentenceSplitter(), timings.reply, 0
        print(f"{self.name}: ", end="", flush=True)
        try:
            for delta in self.llm.stream(messages):
                if chunks == 0:
                    timings.first_token = time.perf_counter() - started
                chunks += 1
                for sentence in splitter.feed(delta):
                    print(sentence, end=" ", flush=True)
                    reply.append(sentence)
                    to_speak.put(sentence)
            if rest := splitter.flush():
                print(rest, end="", flush=True)
                reply.append(rest)
                to_speak.put(rest)
            timings.llm_done = time.perf_counter() - started
            timings.add_llm_stats(self.llm.last_timings, chunks, timings.llm_done)
        finally:
            to_speak.put(None)
            for thread in threads:
                thread.join()
            self.display.publish(state="idle")
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
        return timings


def selftest(mirror: Mirror) -> None:
    """End-to-end check without a mic: synthesise a question, transcribe it, answer it."""
    question = bench.questions(mirror.name)[0]
    stt = SpeechToText(mirror.cfg.stt.model, mirror.cfg.keyterms)
    heard = stt.hear(mirror.voice, question)
    print(f"Asked: {question!r}")
    print(f"Heard: {heard.text!r}  [speech-to-text {heard.stt_seconds:.2f}s]")
    if not heard.text:
        raise SystemExit("Self-test failed: speech-to-text heard nothing.")

    out = mirror.cfg.root / "models" / "selftest_reply.wav"
    mirror.respond(heard.text, time.time(), record_to=out)
    print(f"Reply audio: {out}")


def mic_meter(mirror: Mirror, listening: threading.Event):
    """Separate light mic stream that only measures loudness, to animate the orb."""
    import sounddevice as sd

    last = [0.0]

    def callback(indata, frames, t, status) -> None:
        now = time.time()
        if listening.is_set() and now - last[0] > 0.05:
            last[0] = now
            mirror.display.publish(level=loudness(indata[:, 0]))

    try:
        stream = sd.InputStream(channels=1, samplerate=16000, blocksize=800, callback=callback)
        stream.start()
        return stream
    except Exception as e:  # the orb just won't react to your voice
        print(f"(mic level meter unavailable: {e})")
        return None


def live(mirror: Mirror) -> None:
    from moonshine_voice.mic_transcriber import MicTranscriber

    heard: queue.Queue[tuple[str, float]] = queue.Queue()
    listening = threading.Event()
    listening.set()

    def on_text(text: str) -> None:
        print(f"\r  (hearing) {text[-70:]:<70}", end="", flush=True)
        if listening.is_set():
            mirror.display.publish(state="listening", heard=text)

    mic = (
        MicTranscriber()
        .model_arch(stt_arch(mirror.cfg.stt.model))
        .on_text(on_text)
        .on_line(lambda line: heard.put((line.text.strip(), time.time())))
    )
    print("Loading speech model...")
    mic.load()
    apply_keyterms(mic, mirror.cfg.keyterms)
    mic.start()
    meter = mic_meter(mirror, listening)
    print(f"Listening. Just talk; {mirror.name} answers when you pause. Ctrl+C to quit.\n")
    try:
        while True:
            text, heard_at = heard.get()
            if len(text) < 2:
                continue
            print(f"\rYou: {text:<75}")
            mirror.display.publish(you=text)
            listening.clear()
            mic.mute(True)  # don't transcribe the assistant's own voice from the speakers
            try:
                mirror.respond(text, heard_at)
            finally:
                time.sleep(0.3)
                while not heard.empty():
                    heard.get_nowait()
                mic.mute(False)
                listening.set()
    except KeyboardInterrupt:
        print("\nTa-ra.")
    finally:
        if meter:
            meter.close()
        mic.close()


def preview_voice(cfg: Config, text: str) -> None:
    import sounddevice as sd

    print(f"{cfg.tts.voice}: {text}")
    audio, rate = Voice(cfg.tts).synth(text)
    sd.play(audio, rate)
    sd.wait()


def main() -> None:
    cfg = load_config()
    name = cfg.assistant.name
    parser = argparse.ArgumentParser(description=f"Talk to {name}.")
    parser.add_argument("--selftest", action="store_true", help="test without a microphone")
    parser.add_argument(
        "--bench",
        nargs="?",
        const="all",
        choices=bench.MODES,
        help="time each stage on fixed questions, no mic or speakers: all (default), "
        "tts (voice only, no model server needed) or stt (speech-to-text only)",
    )
    parser.add_argument(
        "--rounds", type=int, default=1, metavar="N", help="with --bench: repeat N times"
    )
    parser.add_argument("--voices", action="store_true", help="list available voices")
    parser.add_argument("--say", metavar="TEXT", help=f"speak TEXT in {name}'s voice and exit")
    parser.add_argument("--voice", metavar="ID", help="override the configured voice")
    args = parser.parse_args()

    if args.voice:
        cfg = replace(cfg, tts=replace(cfg.tts, voice=args.voice))
    if args.voices:
        print(f"Voices for {cfg.tts.language} (current: {cfg.tts.voice}):")
        print("\n".join(f"  {v}" for v in available_voices(cfg.tts.language)))
        return
    if args.say:
        preview_voice(cfg, args.say)
        return

    mirror = Mirror(cfg)
    if args.bench in ("tts", "stt"):  # no model server needed
        bench.run(mirror, args.bench, args.rounds)
        return
    try:
        mirror.llm.check()
    except LLMUnavailable as e:
        sys.exit(str(e))

    if args.selftest:
        selftest(mirror)
        return
    if args.bench:
        bench.run(mirror, args.bench, args.rounds)
        return

    if cfg.display.enabled:
        server = DisplayServer(cfg.root / "display", cfg.display.port, mirror.display).start()
        print(f"Display: {server.url}")
        if cfg.display.open_browser:
            webbrowser.open(server.url)
        # Widget fetch failures are logged as warnings and shown as stale on the display.
        logging.basicConfig(level=logging.WARNING, format="\n(%(message)s)")
        Hub(cfg.widgets, mirror.display.publish).start()
    live(mirror)


if __name__ == "__main__":
    main()
