# Ubuntu 24.04 laptop setup (native install)

## Packages
sudo apt install -y git python3-venv python3-pip libportaudio2 portaudio19-dev cmake ffmpeg espeak-ng

## Robot network (wired, fixed IP; robot is 192.168.123.161)
sudo nmcli connection modify "Wired connection 1" connection.autoconnect no
sudo nmcli connection add type ethernet ifname enp12s0 con-name go2-wired \
  ipv4.method manual ipv4.addresses 192.168.123.99/24 ipv6.method disabled
sudo nmcli connection up go2-wired
ping -c 3 192.168.123.161

## Unitree SDK (env: ~/unitree-env)
python3 -m venv ~/unitree-env && source ~/unitree-env/bin/activate
# build CycloneDDS first (pip cannot find it on Ubuntu 24.04)
git clone https://github.com/eclipse-cyclonedds/cyclonedds -b releases/0.10.x ~/cyclonedds
mkdir ~/cyclonedds/build ~/cyclonedds/install && cd ~/cyclonedds/build
cmake .. -DCMAKE_INSTALL_PREFIX=../install && cmake --build . --target install
export CYCLONEDDS_HOME="$HOME/cyclonedds/install"     # also put in ~/.bashrc
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git ~/unitree_sdk2_python
cd ~/unitree_sdk2_python && pip install -e .

## Checks (robot must be standing; remote in hand for anything that moves it)
python scripts/read_state.py enp12s0     # read only
python scripts/hello_test.py enp12s0     # robot waves

## Voice (see docs/voice.md)
pip install vosk sounddevice pyyaml
python scripts/voice_hello.py --dry-run --name robot

## Known problems
- Robot speaker via WebRTC (scripts/robot_say.py): works up to the handshake over the cable,
  then needs the per-robot AES key (firmware >= 1.1.15). Fetching it from Unitree's cloud failed
  (HTTP 567 / empty reply); needs the Unitree Go account the robot is bound to.
- Small Vosk model hears free speech poorly; use --wake-only (default in voice_hello.py).
