#!/usr/bin/env python3
"""
cmd_vel_bridge.py  -  Nav2 /cmd_vel  ->  Unitree Go2 SportClient.Move

Safety features:
  1. CLAMP     every command is limited to max speeds (defaults are slow).
  2. WATCHDOG  if no /cmd_vel arrives for --timeout seconds, StopMove() is called.
  3. STAND-UP  with --stand the robot is stood up before walking commands start.
  4. DRY-RUN   with --dry-run nothing is sent to the robot, commands are printed.

Usage:
  python3 cmd_vel_bridge.py eth0 --dry-run
  python3 cmd_vel_bridge.py eth0 --stand --max-vx 0.2 --max-vy 0.1 --max-vyaw 0.4

Test by hand (second terminal):
  ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist \
      "{linear: {x: 0.1}, angular: {z: 0.0}}"
  then stop publishing (Ctrl+C) and check that "WATCHDOG" appears after 0.5 s.

CHECK items (verify on the Jetson, they come from docs, not from our robot):
  - import paths of ChannelFactoryInitialize and SportClient
  - method names StandUp / BalanceStand / StopMove / Move
  - the robot's motion mode must accept Move (normal walking mode)
"""

import argparse
import math
import sys
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


def clamp(value, limit):
    """Limit value to [-limit, +limit]."""
    return max(-limit, min(limit, value))


class CmdVelBridge(Node):
    def __init__(self, args):
        super().__init__("cmd_vel_bridge")
        self.args = args
        self.client = None
        self.last_cmd_time = None      # time of the last valid /cmd_vel
        self.is_stopped = True         # True after we sent StopMove (avoid spamming)

        if not args.dry_run:
            self._init_robot()
        else:
            self.get_logger().info("DRY-RUN: no commands will be sent to the robot")

        self.create_subscription(Twist, args.topic, self.on_cmd_vel, 10)
        # watchdog checks 20 times per second
        self.create_timer(0.05, self.watchdog)

        self.get_logger().info(
            f"Limits: vx={args.max_vx} vy={args.max_vy} vyaw={args.max_vyaw} | "
            f"watchdog timeout={args.timeout}s | topic={args.topic}"
        )

    # ---------- robot setup ----------
    def _init_robot(self):
        # Imported here so --dry-run works on a machine without the Unitree SDK.
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize   # CHECK path
        from unitree_sdk2py.go2.sport.sport_client import SportClient      # CHECK path

        ChannelFactoryInitialize(0, self.args.interface)
        self.client = SportClient()
        self.client.SetTimeout(3.0)
        self.client.Init()
        self.get_logger().info(f"Connected to robot on interface {self.args.interface}")

        if self.args.stand:
            self.get_logger().warn("Standing up in 3 s. Clear area, remote ready!")
            time.sleep(3.0)
            self.client.StandUp()          # CHECK name
            time.sleep(2.0)
            self.client.BalanceStand()     # CHECK name, needed before Move
            time.sleep(1.0)
            self.get_logger().info("Stand-up done")
        else:
            self.get_logger().warn(
                "Not standing the robot (no --stand). Make sure it is already "
                "standing in walking mode, otherwise Move() is ignored."
            )

    # ---------- callbacks ----------
    def on_cmd_vel(self, msg: Twist):
        vx, vy, vyaw = msg.linear.x, msg.linear.y, msg.angular.z

        # reject bad numbers
        if any(math.isnan(v) or math.isinf(v) for v in (vx, vy, vyaw)):
            self.get_logger().error("NaN/inf in /cmd_vel, ignoring (watchdog will stop)")
            return

        # 1. CLAMP
        cvx = clamp(vx, self.args.max_vx)
        cvy = clamp(vy, self.args.max_vy)
        cvyaw = clamp(vyaw, self.args.max_vyaw)
        if (cvx, cvy, cvyaw) != (vx, vy, vyaw):
            self.get_logger().warn(
                f"CLAMPED ({vx:.2f}, {vy:.2f}, {vyaw:.2f}) -> "
                f"({cvx:.2f}, {cvy:.2f}, {cvyaw:.2f})",
                throttle_duration_sec=1.0,
            )

        self.last_cmd_time = time.monotonic()
        self.is_stopped = False
        self.send_move(cvx, cvy, cvyaw)

    def watchdog(self):
        """2. WATCHDOG: stop if commands stop arriving."""
        if self.last_cmd_time is None or self.is_stopped:
            return
        if time.monotonic() - self.last_cmd_time > self.args.timeout:
            self.get_logger().warn(
                f"WATCHDOG: no /cmd_vel for {self.args.timeout}s -> StopMove"
            )
            self.stop()

    # ---- robot calls ----
    def send_move(self, vx, vy, vyaw):
        if self.args.dry_run:
            print(f"[dry-run] Move(vx={vx:.2f}, vy={vy:.2f}, vyaw={vyaw:.2f})", flush=True)
            return
        code = self.client.Move(vx, vy, vyaw)
        if code != 0:
            self.get_logger().error(f"Move returned code {code}", throttle_duration_sec=1.0)

    def stop(self):
        self.is_stopped = True
        if self.args.dry_run:
            print("[dry-run] StopMove()", flush=True)
            return
        self.client.StopMove()


def parse_args():
    p = argparse.ArgumentParser(description="Nav2 /cmd_vel -> Unitree Go2 bridge")
    p.add_argument("interface", help="network interface to the robot, e.g. eth0 (ignored in --dry-run)",
                   nargs="?", default="eth0")
    p.add_argument("--dry-run", action="store_true", help="print commands, do not move the robot")
    p.add_argument("--stand", action="store_true", help="stand the robot up at startup")
    p.add_argument("--topic", default="/cmd_vel")
    p.add_argument("--timeout", type=float, default=0.5, help="watchdog timeout in seconds")
    p.add_argument("--max-vx", type=float, default=0.2, help="max forward/back speed (m/s)")
    p.add_argument("--max-vy", type=float, default=0.1, help="max sideways speed (m/s)")
    p.add_argument("--max-vyaw", type=float, default=0.4, help="max turn speed (rad/s)")
    # rclpy may add its own args, so only parse ours
    return p.parse_args(rclpy.utilities.remove_ros_args(sys.argv)[1:])


def main():
    rclpy.init()
    args = parse_args()
    node = CmdVelBridge(args)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # always try to stop the robot on exit
        try:
            node.stop()
        except Exception as e:  # noqa: BLE001
            print(f"Could not send StopMove on exit: {e}")
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
