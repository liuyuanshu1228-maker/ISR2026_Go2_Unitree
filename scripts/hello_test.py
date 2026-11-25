"""First command test: robot waves. Needs the robot standing, remote in hand."""
import sys
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.go2.sport.sport_client import SportClient

iface = sys.argv[1] if len(sys.argv) > 1 else "enp12s0"
if input("Remote in hand, clear space, robot standing? Type yes: ").strip().lower() != "yes":
    sys.exit("Cancelled.")
ChannelFactoryInitialize(0, iface)
sport = SportClient()
sport.SetTimeout(10.0)
sport.Init()
print("Hello code:", sport.Hello())   # 0 = accepted
