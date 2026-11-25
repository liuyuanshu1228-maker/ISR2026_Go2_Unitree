# Voice wake (the robot hears us and notices its name)

Script: `scripts/voice_wake.py` · config: `config/voice_wake.yaml` · tests: `scripts/test_voice_wake.py`

## How it works

```
USB microphone (16 kHz mono) --Vosk offline ASR--> sentence text
      --WakeMatcher (fuzzy name match, cooldown)--> /voice/wake
                                          every sentence --> /voice/transcript
```

| Topic | Type | Meaning |
|---|---|---|
| `/voice/transcript` | std_msgs/String | every sentence the robot heard |
| `/voice/wake` | std_msgs/String | the name was said. `data` = words after the name (`""` if only the name), e.g. `"come here"` |

The HRI / behaviour-selection node subscribes to `/voice/wake` and decides what to do
(turn toward the speaker, stand, wave...). Motion still goes through the normal
safety chain (`cmd_vel_bridge.py`, Stage limits, e-stop). Voice must never bypass it.

## Install (Jetson, Ubuntu)

```
sudo apt install -y libportaudio2 portaudio19-dev
pip install vosk sounddevice pyyaml
mkdir -p models && cd models
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip && unzip vosk-model-small-en-us-0.15.zip
```
`models/` is not committed (add it to .gitignore).

## Run

```
python3 scripts/voice_wake.py --list-devices            # find the mic index, put it in config/voice_wake.yaml
python3 scripts/voice_wake.py --dry-run                 # print only, no ROS
python3 scripts/voice_wake.py                           # publish to ROS 2
ros2 topic echo /voice/wake
```

Tests without robot or mic (Mac is fine):
```
python3 -m pytest scripts/test_voice_wake.py
python3 scripts/voice_wake.py --dry-run --text "momo come here" --name momo
python3 scripts/voice_wake.py --dry-run --wav sample.wav     # 16 kHz mono 16-bit wav
```

## Choosing the name (important)

"go two" is heard as "go to" / "go too" (handled), but "go to the lift" is also a normal
sentence for us, so it would trigger by accident. Use a name that is not an everyday phrase,
e.g. `momo`, and keep "go two" only if you accept false triggers. Set it in `config/voice_wake.yaml`.

## CHECK on the robot

- Microphone: the Go2 body mic is not exposed to the Jetson by default (CHECK). Plan on a USB mic
  (or USB conference speakerphone) plugged into the Jetson. Test with `arecord -l`.
- Motor/fan noise while the robot walks lowers accuracy. Place the mic away from the legs/fans;
  measure the hit rate walking vs standing and log it like the other trials.
- CPU: the small model is light; check with `scripts/cpu_logger.py` (feeds Yuanshu's cost experiments).
- Privacy: transcripts are published but not saved. Do not record audio of people without consent
  (project ethics rules); `--wav` is for our own test recordings only.
