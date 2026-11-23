#!/usr/bin/env python3
"""
navigation.launch.py  -  Go2 iSR 2026  (ROS 2 Humble)   Owner: Jingyu

Starts:  localization.launch.py (Yuanshu)  +  Nav2 (controller, planner, behaviours,
         BT navigator, waypoint follower)  +  velocity smoother  +  collision monitor
         +  cmd_vel_bridge.py

Velocity chain:
  controller/behaviours -> /cmd_vel_nav -> velocity_smoother -> /cmd_vel_smoothed
  -> collision_monitor -> /cmd_vel -> cmd_vel_bridge.py -> Go2

Examples
  # Docker / Mac, no robot (bridge prints commands only, this is the default):
  ros2 launch launch/navigation.launch.py use_sim_time:=false

  # Real robot, first test, robot already standing:
  ros2 launch launch/navigation.launch.py dry_run:=false interface:=eth0

  # Real robot, stand up first:
  ros2 launch launch/navigation.launch.py dry_run:=false interface:=eth0 stand:=true

  # Foxy fallback (no smoother, no collision monitor):
  ros2 launch launch/navigation.launch.py humble_nodes:=false

Interface agreed with Yuanshu: launch/localization.launch.py must accept the
launch arguments  use_sim_time, map, params_file  (CHECK once her file exists).
"""

import os

from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess,
                            IncludeLaunchDescription, LogInfo, OpaqueFunction)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from nav2_common.launch import RewrittenYaml

HERE = os.path.dirname(os.path.realpath(__file__))     # .../launch
REPO = os.path.dirname(HERE)                            # repo root


def _flag(context, name):
    return LaunchConfiguration(name).perform(context).strip().lower() in ("true", "1", "yes")


def setup(context):
    use_sim_time = LaunchConfiguration("use_sim_time")
    humble_nodes = _flag(context, "humble_nodes")

    # Same params file for sim and robot: only use_sim_time is overridden.
    params = RewrittenYaml(
        source_file=LaunchConfiguration("params_file"),
        root_key="",
        param_rewrites={"use_sim_time": use_sim_time},
        convert_types=True,
    )

    # Where the controller / behaviours publish.
    nav_cmd_topic = "cmd_vel_nav" if humble_nodes else "cmd_vel"
    nav_remap = [("cmd_vel", nav_cmd_topic)]

    def nav2_node(package, executable, name, remappings=None):
        return Node(package=package, executable=executable, name=name,
                    output="screen", parameters=[params],
                    remappings=remappings or [])

    actions = [
        nav2_node("nav2_controller", "controller_server", "controller_server", nav_remap),
        nav2_node("nav2_planner", "planner_server", "planner_server"),
        nav2_node("nav2_behaviors", "behavior_server", "behavior_server", nav_remap),
        nav2_node("nav2_bt_navigator", "bt_navigator", "bt_navigator"),
        nav2_node("nav2_waypoint_follower", "waypoint_follower", "waypoint_follower"),
    ]
    managed = ["controller_server", "planner_server", "behavior_server",
               "bt_navigator", "waypoint_follower"]

    if humble_nodes:
        # smoother reads /cmd_vel_nav and publishes /cmd_vel_smoothed (params file)
        actions.append(nav2_node("nav2_velocity_smoother", "velocity_smoother",
                                 "velocity_smoother", [("cmd_vel", "cmd_vel_nav")]))
        # monitor reads /cmd_vel_smoothed and publishes /cmd_vel (params file)
        actions.append(nav2_node("nav2_collision_monitor", "collision_monitor",
                                 "collision_monitor"))
        managed += ["velocity_smoother", "collision_monitor"]
    else:
        actions.append(LogInfo(msg="humble_nodes:=false -> no velocity smoother, no "
                                   "collision monitor. Nav2 publishes /cmd_vel directly."))

    actions.append(Node(
        package="nav2_lifecycle_manager", executable="lifecycle_manager",
        name="lifecycle_manager_navigation", output="screen",
        parameters=[{"use_sim_time": use_sim_time, "autostart": True,
                     "node_names": managed}]))

    # ---- bridge to the robot --------------------------------------------------
    if _flag(context, "bridge"):
        dry_run = _flag(context, "dry_run")
        cmd = ["python3", os.path.join(REPO, "scripts", "cmd_vel_bridge.py"),
               LaunchConfiguration("interface").perform(context)]
        if dry_run:
            cmd.append("--dry-run")
        if _flag(context, "stand") and not dry_run:
            cmd.append("--stand")
        for flag, arg in (("--max-vx", "max_vx"), ("--max-vy", "max_vy"),
                          ("--max-vyaw", "max_vyaw")):
            cmd += [flag, LaunchConfiguration(arg).perform(context)]
        mode = "DRY-RUN (robot will NOT move)" if dry_run else "REAL ROBOT: remote holder ready!"
        actions.append(LogInfo(msg=f"cmd_vel_bridge: {mode}"))
        actions.append(ExecuteProcess(cmd=cmd, output="screen"))

    return actions


def generate_launch_description():
    declare = [
        DeclareLaunchArgument("use_sim_time", default_value="false",
                              description="true in simulation, false on the robot"),
        DeclareLaunchArgument("params_file",
                              default_value=os.path.join(REPO, "config", "nav2_params.yaml")),
        DeclareLaunchArgument("map",
                              default_value=os.path.join(REPO, "maps", "soit_map.yaml")),
        DeclareLaunchArgument("localization", default_value="true",
                              description="include localization.launch.py (map_server + AMCL + sensors)"),
        DeclareLaunchArgument("humble_nodes", default_value="true",
                              description="false on Foxy: skips velocity smoother and collision monitor"),
        DeclareLaunchArgument("bridge", default_value="true",
                              description="start cmd_vel_bridge.py"),
        DeclareLaunchArgument("dry_run", default_value="true",
                              description="bridge only prints commands (SAFE DEFAULT). Use false on the robot"),
        DeclareLaunchArgument("stand", default_value="false",
                              description="bridge stands the robot up at startup (needs dry_run:=false)"),
        DeclareLaunchArgument("interface", default_value="eth0",
                              description="network interface to the Go2"),
        DeclareLaunchArgument("max_vx", default_value="0.2"),
        DeclareLaunchArgument("max_vy", default_value="0.1"),
        DeclareLaunchArgument("max_vyaw", default_value="0.4"),
    ]

    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(HERE, "localization.launch.py")),
        launch_arguments={
            "use_sim_time": LaunchConfiguration("use_sim_time"),
            "map": LaunchConfiguration("map"),
            "params_file": LaunchConfiguration("params_file"),
        }.items(),
        condition=IfCondition(LaunchConfiguration("localization")),
    )

    return LaunchDescription(declare + [localization, OpaqueFunction(function=setup)])
