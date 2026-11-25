#!/usr/bin/env python3
"""Robot hears its name -> waves (Hello). No ROS needed.

  python scripts/voice_hello.py --dry-run --name robot   # prints only, robot does nothing
  python scripts/voice_hello.py --name robot             # real: sends Hello to the Go2
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voice_wake as vw  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Wave when the robot's name is heard.")
    p.add_argument("--iface", default="enp12s0", help="network interface to the robot")
    p.add_argument("--name", action="append", help="wake name (repeatable)")
    p.add_argument("--device", type=int, help="microphone index")
    p.add_argument("--model", help="Vosk model folder")
    p.add_argument("--cooldown", type=float, default=10.0, help="seconds between waves")
    p.add_argument("--dry-run", action="store_true", help="do not send commands to the robot")
    p.add_argument("--gain", type=float, default=1.0, help="multiply microphone volume")
    p.add_argument("--full", action="store_true", help="use free speech recognition instead of wake-only")
    p.add_argument("--say-file", help="audio file to play on the laptop's speaker when the name is heard")
    args = p.parse_args()

    cfg = vw.load_config(vw.DEFAULT_CONFIG)
    matcher = vw.WakeMatcher(args.name or cfg["names"], cfg["threshold"], args.cooldown)

    sport = None
    if not args.dry_run:
        if input("Remote in hand, clear space, robot standing? Type yes: ").strip().lower() != "yes":
            sys.exit("Cancelled.")
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        from unitree_sdk2py.go2.sport.sport_client import SportClient
        ChannelFactoryInitialize(0, args.iface)
        sport = SportClient()
        sport.SetTimeout(10.0)
        sport.Init()

    rec = vw.make_recognizer(args.model or cfg["model"], args.name or cfg["names"], grammar=not args.full)
    device = args.device if args.device is not None else cfg["device"]
    print(f"Listening for {args.name or cfg['names']} ... Ctrl+C to stop")
    try:
        for text in vw.sentences(vw.audio_from_mic(device, gain=args.gain), rec, cfg["min_confidence"]):
            print(f"[heard] {text}")
            rest = matcher.check(text)
            if rest is not None:
                print(f"[WAKE ] command part: {rest!r}")
                if args.say_file:
                    subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", args.say_file])
                if sport is not None:
                    print("  Hello code:", sport.Hello())
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
