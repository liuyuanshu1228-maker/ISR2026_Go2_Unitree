#!/usr/bin/env python3
"""
voice_wake.py - the robot hears speech and notices when we call its name.   (Go2 iSR 2026)

Pipeline (all offline, runs on the Jetson, no cloud):

    microphone (16 kHz mono)  --Vosk streaming ASR-->  text
        --WakeMatcher (fuzzy name match + cooldown)-->  wake event

ROS 2 topics published (std_msgs/String):
    /voice/transcript   every finished sentence we heard (for logs / later commands)
    /voice/wake         the robot's name was said. Data = what was said AFTER the name
                        ("" if only the name), e.g. "come here". Other nodes (HRI,
                        behaviour selection) subscribe to this.

Plain-Python core (WakeMatcher, normalize) has no ROS / audio imports, so it runs
and tests on a Mac:  python3 -m pytest scripts/test_voice_wake.py

Examples
  # No robot, no mic: try a recorded 16 kHz mono wav file, print what happens
  python3 scripts/voice_wake.py --dry-run --wav sample.wav --name "go two"

  # Type text instead of speaking (tests only the name matching)
  python3 scripts/voice_wake.py --dry-run --text "hey go two come here"

  # Real microphone, print only (no ROS)
  python3 scripts/voice_wake.py --dry-run --model models/vosk-model-small-en-us-0.15

  # On the Jetson, publish to ROS 2
  python3 scripts/voice_wake.py --model models/vosk-model-small-en-us-0.15 --config config/voice_wake.yaml

  python3 scripts/voice_wake.py --list-devices      # find the microphone index

Install (Jetson / Ubuntu):
  sudo apt install -y libportaudio2 portaudio19-dev
  pip install vosk sounddevice pyyaml
  # model: https://alphacephei.com/vosk/models  (vosk-model-small-en-us-0.15, ~40 MB)
"""

import argparse
import difflib
import json
import queue
import re
import sys
import time
import wave
from pathlib import Path

SAMPLE_RATE = 16000
REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO / "config" / "voice_wake.yaml"

# What the speech recogniser often writes for the digit in "go2".
_NUMBER_WORDS = {"2": "two", "to": "two", "too": "two", "tu": "two"}


# --------------------------------------------------------------------------- #
# Plain-Python core (no ROS, no audio): tested in test_voice_wake.py
# --------------------------------------------------------------------------- #

def normalize(text):
    """Lower-case, keep letters/digits only, split 'go2' -> 'go 2'. Returns a list of words."""
    text = text.lower()
    text = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", text)  # go2 -> go 2
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return text.split()


def _word_similar(a, b, threshold):
    if a == b:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


class WakeMatcher:
    """Decides whether a sentence contains the robot's name.

    names     : list of names/aliases, e.g. ["go two", "momo"]. Multi-word names must
                match as consecutive words.
    threshold : 0..1 how close a heard word must be to a name word (1.0 = exact).
                0.8 forgives "mo mo"/"momu" style recogniser errors.
    cooldown  : seconds to ignore a second trigger (one call is often heard twice,
                as a partial and as a final result).
    """

    def __init__(self, names, threshold=0.8, cooldown=2.0):
        self.names = [normalize(n) for n in names if normalize(n)]
        if not self.names:
            raise ValueError("at least one wake name is needed")
        self.threshold = threshold
        self.cooldown = cooldown
        self._last_trigger = -1e9

    def find(self, text):
        """Return (name_words, rest_of_sentence) if the name is in `text`, else None.
        Does not look at the cooldown, so it is easy to test."""
        words = normalize(text)
        for name in self.names:
            n = len(name)
            for i in range(len(words) - n + 1):
                window = words[i:i + n]
                if all(self._match(w, t) for w, t in zip(window, name)):
                    return " ".join(window), " ".join(words[i + n:])
        return None

    def _match(self, heard, wanted):
        # "go to" / "go too" / "go 2" are all heard for "go two"; only for number words
        if wanted in _NUMBER_WORDS.values() or wanted.isdigit():
            canon = {"2": "two"}.get(wanted, wanted)
            heard_c = _NUMBER_WORDS.get(heard, heard)
            if heard_c == canon:
                return True
        return _word_similar(heard, wanted, self.threshold)

    def check(self, text, now=None):
        """find() plus cooldown. Returns the words said after the name, or None."""
        now = time.monotonic() if now is None else now
        hit = self.find(text)
        if hit is None:
            return None
        if now - self._last_trigger < self.cooldown:
            return None
        self._last_trigger = now
        return hit[1]


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

DEFAULTS = {
    "names": ["go two"],
    "threshold": 0.8,
    "cooldown": 2.0,
    "model": "models/vosk-model-small-en-us-0.15",
    "device": None,          # microphone index from --list-devices; None = system default
    "min_confidence": 0.0,   # drop sentences whose average word confidence is lower
}


def load_config(path):
    cfg = dict(DEFAULTS)
    path = Path(path)
    if path.exists():
        import yaml
        with open(path) as f:
            cfg.update(yaml.safe_load(f) or {})
    return cfg


# --------------------------------------------------------------------------- #
# Speech recognition (Vosk)
# --------------------------------------------------------------------------- #

def make_recognizer(model_path, names=None, grammar=False):
    from vosk import KaldiRecognizer, Model, SetLogLevel
    SetLogLevel(-1)
    if not Path(model_path).exists():
        sys.exit(f"Vosk model not found: {model_path}\n"
                 "Download vosk-model-small-en-us-0.15 from https://alphacephei.com/vosk/models "
                 "and unzip it into models/ (or pass --model).")
    rec = KaldiRecognizer(Model(str(model_path)), SAMPLE_RATE)
    rec.SetWords(True)
    return rec


def sentence_confidence(result):
    words = result.get("result", [])
    return sum(w.get("conf", 1.0) for w in words) / len(words) if words else 0.0


def audio_from_wav(path, block=4000):
    """Yield raw int16 chunks from a 16 kHz mono wav file (for tests without a mic)."""
    with wave.open(str(path), "rb") as wf:
        if (wf.getframerate(), wf.getnchannels(), wf.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            sys.exit(f"{path}: need 16 kHz, mono, 16-bit wav "
                     "(convert: ffmpeg -i in.wav -ar 16000 -ac 1 out.wav)")
        while True:
            data = wf.readframes(block)
            if not data:
                return
            yield data


def audio_from_mic(device=None, block=4000):
    """Yield raw int16 chunks (0.25 s each) from the microphone, forever."""
    import sounddevice as sd
    q = queue.Queue()

    def callback(indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}", file=sys.stderr)
        q.put(bytes(indata))

    with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=block, device=device,
                           dtype="int16", channels=1, callback=callback):
        while True:
            yield q.get()


def sentences(chunks, recognizer, min_confidence=0.0):
    """Turn audio chunks into finished sentences (str)."""
    for chunk in chunks:
        if recognizer.AcceptWaveform(chunk):
            result = json.loads(recognizer.Result())
            text = result.get("text", "").strip()
            if text and sentence_confidence(result) >= min_confidence:
                yield text
    text = json.loads(recognizer.FinalResult()).get("text", "").strip()
    if text:
        yield text


# --------------------------------------------------------------------------- #
# Run loops
# --------------------------------------------------------------------------- #

def handle(text, matcher, publish_transcript, publish_wake):
    publish_transcript(text)
    rest = matcher.check(text)
    if rest is not None:
        publish_wake(rest)


def run_dry(args, cfg, matcher):
    def on_transcript(t):
        print(f"[heard] {t}")

    def on_wake(rest):
        print(f"[WAKE ] name heard! command part: {rest!r}")

    if args.text:
        for line in args.text:
            handle(line, matcher, on_transcript, on_wake)
        return
    rec = make_recognizer(args.model or cfg["model"])
    chunks = audio_from_wav(args.wav) if args.wav else audio_from_mic(
        args.device if args.device is not None else cfg["device"])
    print("Listening... Ctrl+C to stop" if not args.wav else f"Reading {args.wav}")
    try:
        for text in sentences(chunks, rec, cfg["min_confidence"]):
            handle(text, matcher, on_transcript, on_wake)
    except KeyboardInterrupt:
        pass


def run_ros(args, cfg, matcher):
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String

    class VoiceWakeNode(Node):
        def __init__(self):
            super().__init__("voice_wake")
            self.pub_text = self.create_publisher(String, "/voice/transcript", 10)
            self.pub_wake = self.create_publisher(String, "/voice/wake", 10)

        def transcript(self, text):
            self.get_logger().info(f"heard: {text}")
            self.pub_text.publish(String(data=text))

        def wake(self, rest):
            self.get_logger().info(f"WAKE (command: {rest!r})")
            self.pub_wake.publish(String(data=rest))

    rclpy.init()
    node = VoiceWakeNode()
    rec = make_recognizer(args.model or cfg["model"])
    chunks = audio_from_wav(args.wav) if args.wav else audio_from_mic(
        args.device if args.device is not None else cfg["device"])
    node.get_logger().info(f"listening for {cfg['names']}")
    try:
        for text in sentences(chunks, rec, cfg["min_confidence"]):
            handle(text, matcher, node.transcript, node.wake)
            rclpy.spin_once(node, timeout_sec=0)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


def main():
    p = argparse.ArgumentParser(description="Hear speech and detect the robot's name.")
    p.add_argument("--config", default=str(DEFAULT_CONFIG), help="YAML config (config/voice_wake.yaml)")
    p.add_argument("--name", action="append", help="wake name (repeat for aliases); overrides config")
    p.add_argument("--model", help="path to a Vosk model folder; overrides config")
    p.add_argument("--device", type=int, help="microphone index (see --list-devices)")
    p.add_argument("--wav", help="read this 16 kHz mono wav instead of the microphone")
    p.add_argument("--text", action="append", help="test sentence instead of audio (repeatable)")
    p.add_argument("--dry-run", action="store_true", help="print only, do not use ROS 2")
    p.add_argument("--list-devices", action="store_true", help="list audio input devices and exit")
    args = p.parse_args()

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return

    cfg = load_config(args.config)
    if args.name:
        cfg["names"] = args.name
    matcher = WakeMatcher(cfg["names"], cfg["threshold"], cfg["cooldown"])

    (run_dry if args.dry_run else run_ros)(args, cfg, matcher)


if __name__ == "__main__":
    main()
