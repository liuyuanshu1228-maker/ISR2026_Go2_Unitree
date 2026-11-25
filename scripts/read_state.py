"""Read-only: print the Go2's sport-mode state. Sends NO commands."""
import sys
import time
from dataclasses import fields

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_

iface = sys.argv[1] if len(sys.argv) > 1 else "enp12s0"
ChannelFactoryInitialize(0, iface)

count = 0
def handler(msg: SportModeState_):
    global count
    if count == 0:
        print("FIELDS:", [f.name for f in fields(msg)])
    if count % 50 == 0:          # about once per second
        print(f"mode={msg.mode} gait={msg.gait_type} body_height={msg.body_height:.3f} "
              f"pos={[round(x, 3) for x in msg.position]} "
              f"vel={[round(x, 3) for x in msg.velocity]} yaw_speed={msg.yaw_speed:.3f}")
    count += 1

sub = ChannelSubscriber("rt/sportmodestate", SportModeState_)
sub.Init(handler, 10)
print(f"Listening on {iface} for 15 s (read only)...")
time.sleep(15)
print(f"Messages received: {count}")
