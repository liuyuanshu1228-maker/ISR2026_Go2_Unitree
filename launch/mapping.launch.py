#!/usr/bin/env python3
"""
mapping.launch.py  -  Go2 iSR 2026  (ROS 2 Humble)   Owner: Yuanshu

Builds the map once (research notes #1, SLAM). Starts:
  1. Livox driver (livox_ros_driver2)        -> /livox/lidar  (PointCloud2, livox_frame)
  2. static TF base_link -> livox_frame      (placeholder numbers, measure on Wednesday)
  3. odom_publisher.py (Jingyu)              -> /odom + TF odom -> base_footprint -> base_link
  4. pointcloud_to_laserscan                 -> /scan_raw
  5. body box filter (laser_filters)         -> /scan
  6. slam_toolbox (async, mapping)           -> /map + TF map -> odom
  7. Foxglove bridge                         -> ws://<host>:8765

Frames: map -> odom -> base_footprint -> base_link -> livox_frame

Examples
  # Real robot (Jetson), first mapping walk:
  ros2 launch launch/mapping.launch.py host_ip:=192.168.1.50

  # Measured LiDAR position (Wednesday):
  ros2 launch launch/mapping.launch.py lidar_x:=0.18 lidar_z:=0.12

  # Docker on a Mac, no robot: fake odom TF, no driver, just check everything starts
  ros2 launch launch/mapping.launch.py lidar:=false odom:=fake

  # Sample rosbag that already has /livox/lidar (PointCloud2) and odom TF:
  ros2 launch launch/mapping.launch.py lidar:=false odom:=none use_sim_time:=true
  ros2 bag play <bag> --clock

  # Save the map when the walk is done:
  ros2 run nav2_map_server map_saver_cli -f maps/soit_map

Missing optional packages (Livox driver, Foxglove bridge) and a missing
odom_publisher.py are reported and skipped, so the rest still starts.
"""

import json
import os
import tempfile

from ament_index_python.packages import (PackageNotFoundError,
                                         get_package_share_directory)
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess, LogInfo,
                            OpaqueFunction)
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

HERE = os.path.dirname(os.path.realpath(__file__))     # .../launch
REPO = os.path.dirname(HERE)                            # repo root
CONFIG = os.path.join(REPO, "config")

ODOM_CHOICES = ("real", "fake", "none")


def _arg(context, name):
    return LaunchConfiguration(name).perform(context).strip()


def _flag(context, name):
    return _arg(context, name).lower() in ("true", "1", "yes")


def _have_package(name):
    try:
        get_package_share_directory(name)
        return True
    except PackageNotFoundError:
        return False


def livox_config(context):
    """Return the Livox JSON to use. If host_ip / lidar_ip are given, write a
    patched copy to /tmp so the file in the repo stays unchanged."""
    path = _arg(context, "livox_config")
    host_ip, lidar_ip = _arg(context, "host_ip"), _arg(context, "lidar_ip")
    if not host_ip and not lidar_ip:
        return path

    with open(path) as f:
        cfg = json.load(f)
    if host_ip:
        host = cfg["MID360"]["host_net_info"]
        for key in ("cmd_data_ip", "push_msg_ip", "point_data_ip", "imu_data_ip"):
            host[key] = host_ip
    if lidar_ip:
        cfg["lidar_configs"][0]["ip"] = lidar_ip

    fd, patched = tempfile.mkstemp(prefix="MID360_", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
    return patched


def static_tf(name, parent, child, x="0", y="0", z="0", roll="0", pitch="0", yaw="0",
              use_sim_time="false"):
    return Node(
        package="tf2_ros", executable="static_transform_publisher", name=name,
        output="screen",
        arguments=["--x", x, "--y", y, "--z", z,
                   "--roll", roll, "--pitch", pitch, "--yaw", yaw,
                   "--frame-id", parent, "--child-frame-id", child],
        parameters=[{"use_sim_time": use_sim_time == "true"}])


def setup(context):
    use_sim_time = _arg(context, "use_sim_time").lower()
    sim = use_sim_time == "true"
    actions = []

    # ---- 1. Livox driver ---------------------------------------------------
    if _flag(context, "lidar"):
        if _have_package("livox_ros_driver2"):
            cfg = livox_config(context)
            actions.append(LogInfo(msg=f"Livox driver config: {cfg}"))
            actions.append(Node(
                package="livox_ros_driver2", executable="livox_ros_driver2_node",
                name="livox_lidar_publisher", output="screen",
                parameters=[{
                    "xfer_format": 0,          # 0 = sensor_msgs/PointCloud2 (not CustomMsg)
                    "multi_topic": 0,          # one topic: /livox/lidar
                    "data_src": 0,             # live LiDAR
                    "publish_freq": 10.0,      # Hz
                    "output_data_type": 0,
                    "frame_id": "livox_frame",
                    "user_config_path": cfg,
                    "cmdline_input_bd_code": "livox0000000001",
                    "use_sim_time": sim,
                }]))
        else:
            actions.append(LogInfo(msg="WARNING: livox_ros_driver2 not found (build "
                                       "Livox-SDK2 + livox_ros_driver2 in the workspace). "
                                       "Skipping the driver; use lidar:=false to silence this."))

    # ---- 2. LiDAR position on the body -------------------------------------
    actions.append(static_tf(
        "lidar_static_tf", "base_link", "livox_frame",
        *(_arg(context, f"lidar_{k}") for k in ("x", "y", "z", "roll", "pitch", "yaw")),
        use_sim_time=use_sim_time))

    # ---- 3. Odometry ---------------------------------------------------------
    odom = _arg(context, "odom").lower()
    if odom not in ODOM_CHOICES:
        raise RuntimeError(f"odom:={odom} is not one of {ODOM_CHOICES}")
    if odom == "real":
        script = os.path.join(REPO, "scripts", "odom_publisher.py")
        if os.path.exists(script):
            # Real robot only (wall clock), so no use_sim_time is passed.
            actions.append(ExecuteProcess(cmd=["python3", script], output="screen"))
        else:
            actions.append(LogInfo(msg="WARNING: scripts/odom_publisher.py (Jingyu) not "
                                       "found. No odom TF, slam_toolbox will wait. "
                                       "Use odom:=fake to test without it."))
    elif odom == "fake":
        # Robot never moves: good enough to check that everything starts.
        actions.append(LogInfo(msg="odom:=fake -> static odom -> base_footprint -> base_link"))
        actions.append(static_tf("fake_odom_tf", "odom", "base_footprint",
                                 use_sim_time=use_sim_time))
        actions.append(static_tf("fake_body_tf", "base_footprint", "base_link",
                                 z=_arg(context, "body_height"), use_sim_time=use_sim_time))
    # odom == "none": the bag / simulator provides the odom TF.

    # ---- 4 + 5. 3D cloud -> 2D scan, then remove the robot's own body -------
    body_filter = _flag(context, "body_filter")
    actions.append(Node(
        package="pointcloud_to_laserscan", executable="pointcloud_to_laserscan_node",
        name="pointcloud_to_laserscan", output="screen",
        parameters=[os.path.join(CONFIG, "pointcloud_to_laserscan.yaml"),
                    {"use_sim_time": sim}],
        remappings=[("cloud_in", _arg(context, "cloud_topic")),
                    ("scan", "/scan_raw" if body_filter else "/scan")]))
    if body_filter:
        actions.append(Node(
            package="laser_filters", executable="scan_to_scan_filter_chain",
            name="scan_to_scan_filter_chain", output="screen",
            parameters=[os.path.join(CONFIG, "scan_filter.yaml"), {"use_sim_time": sim}],
            remappings=[("scan", "/scan_raw"), ("scan_filtered", "/scan")]))

    # ---- 6. SLAM -------------------------------------------------------------
    if _flag(context, "slam"):
        actions.append(Node(
            package="slam_toolbox", executable="async_slam_toolbox_node",
            name="slam_toolbox", output="screen",
            parameters=[_arg(context, "slam_params"), {"use_sim_time": sim}]))

    # ---- 7. Foxglove (view from the Macs) ------------------------------------
    if _flag(context, "foxglove"):
        if _have_package("foxglove_bridge"):
            actions.append(Node(
                package="foxglove_bridge", executable="foxglove_bridge",
                name="foxglove_bridge", output="screen",
                parameters=[{"port": int(_arg(context, "foxglove_port")),
                             "use_sim_time": sim}]))
        else:
            actions.append(LogInfo(msg="WARNING: foxglove_bridge not installed "
                                       "(apt install ros-humble-foxglove-bridge). Skipping."))

    return actions


def generate_launch_description():
    declare = [
        DeclareLaunchArgument("use_sim_time", default_value="false",
                              description="true when playing a rosbag with --clock"),
        DeclareLaunchArgument("lidar", default_value="true",
                              description="start the Livox driver (false for rosbag / Docker)"),
        DeclareLaunchArgument("livox_config",
                              default_value=os.path.join(CONFIG, "MID360_config.json")),
        DeclareLaunchArgument("host_ip", default_value="",
                              description="Jetson IP on the LiDAR network (overrides the JSON). CHECK"),
        DeclareLaunchArgument("lidar_ip", default_value="",
                              description="Mid-360 IP (overrides the JSON, default 192.168.1.166). CHECK"),
        DeclareLaunchArgument("cloud_topic", default_value="/livox/lidar",
                              description="PointCloud2 input of the scan slice"),
        DeclareLaunchArgument("odom", default_value="real",
                              description="real = odom_publisher.py, fake = static TF, none = from bag"),
        DeclareLaunchArgument("body_height", default_value="0.30",
                              description="base_footprint -> base_link z, only used with odom:=fake"),
        DeclareLaunchArgument("body_filter", default_value="true",
                              description="remove the robot's own body from /scan (needs laser_filters)"),
        DeclareLaunchArgument("slam", default_value="true", description="start slam_toolbox"),
        DeclareLaunchArgument("slam_params",
                              default_value=os.path.join(CONFIG, "slam_toolbox.yaml")),
        DeclareLaunchArgument("foxglove", default_value="true", description="start Foxglove bridge"),
        DeclareLaunchArgument("foxglove_port", default_value="8765"),
        # base_link -> livox_frame. Placeholders from the plan; measure on Wednesday.
        DeclareLaunchArgument("lidar_x", default_value="0.15", description="m forward. CHECK"),
        DeclareLaunchArgument("lidar_y", default_value="0.0", description="m left. CHECK"),
        DeclareLaunchArgument("lidar_z", default_value="0.15", description="m up. CHECK"),
        DeclareLaunchArgument("lidar_roll", default_value="0.0", description="rad. CHECK"),
        DeclareLaunchArgument("lidar_pitch", default_value="0.0", description="rad. CHECK"),
        DeclareLaunchArgument("lidar_yaw", default_value="0.0", description="rad. CHECK"),
    ]
    return LaunchDescription(declare + [OpaqueFunction(function=setup)])
