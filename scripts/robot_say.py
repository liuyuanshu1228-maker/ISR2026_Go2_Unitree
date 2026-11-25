"""Play an audio file through the Go2's speaker (WebRTC). Usage: python robot_say.py yes.mp3 [seconds]"""
import asyncio
import os
import sys

from aiortc.contrib.media import MediaPlayer
from unitree_webrtc_connect.webrtc_driver import UnitreeWebRTCConnection, WebRTCConnectionMethod

ROBOT_IP = os.environ.get("UNITREE_ROBOT_IP", "192.168.123.161")
KEY = os.environ.get("UNITREE_AES_128_KEY")   # only needed on firmware 1.1.15+


async def main(path, seconds):
    kwargs = {"ip": ROBOT_IP}
    if KEY:
        kwargs["aes_128_key"] = KEY
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, **kwargs)
    print("Connecting to", ROBOT_IP, "...")
    await conn.connect()
    print("Connected. Playing", path)
    player = MediaPlayer(path)
    conn.pc.addTrack(player.audio)
    await asyncio.sleep(seconds)
    print("Done.")


if __name__ == "__main__":
    path = os.path.expanduser(sys.argv[1])
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 6
    asyncio.run(main(path, seconds))
    os._exit(0)
