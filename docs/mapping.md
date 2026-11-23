# Mapping (LiDAR + SLAM) runbook · Owner: Yuanshu

Plan section #1. Builds `maps/soit_map.yaml` once; localisation (AMCL) uses it after.

## Pipeline

```
Mid-360 --livox_ros_driver2--> /livox/lidar (PointCloud2, livox_frame)
        --pointcloud_to_laserscan (0.10-1.0 m slice)--> /scan_raw
        --laser_filters box (removes the robot body)--> /scan
        --slam_toolbox--> /map + TF map -> odom
odom_publisher.py (Jingyu) --> /odom + TF odom -> base_footprint -> base_link
static TF base_link -> livox_frame (launch args lidar_x ... lidar_yaw)
```

| File | What |
|---|---|
| `config/MID360_config.json` | Livox driver: LiDAR IP 192.168.1.166, host IP placeholder 192.168.1.50 (CHECK) |
| `config/pointcloud_to_laserscan.yaml` | 3D to 2D slice |
| `config/scan_filter.yaml` | body box filter (body + 5 cm) |
| `config/slam_toolbox.yaml` | SLAM settings |
| `launch/mapping.launch.py` | starts all of the above + Foxglove bridge |
| `scripts/check_sensors.sh` | ping, topic rates, TF chain |
| `scripts/cpu_logger.py` | CPU / memory per process during a trial (cpu_avg) |

## Install (Docker or Jetson, Humble)

```
apt install -y ros-humble-slam-toolbox ros-humble-pointcloud-to-laserscan \
  ros-humble-laser-filters ros-humble-foxglove-bridge ros-humble-nav2-map-server python3-psutil
```
Livox: build Livox-SDK2 and livox_ros_driver2 (`./build.sh humble`) in the workspace and source it.

## Run

```
# Docker, no robot: check everything starts
ros2 launch launch/mapping.launch.py lidar:=false odom:=fake

# Robot (Wednesday)
ros2 launch launch/mapping.launch.py host_ip:=<jetson ip> lidar_x:=<m> lidar_z:=<m>
scripts/check_sensors.sh
# walk slowly, close a loop, then:
ros2 run nav2_map_server map_saver_cli -f maps/soit_map
```

Sample bag test: `ros2 bag info <bag>` first. It needs `sensor_msgs/PointCloud2`
(not `livox_ros_driver2/CustomMsg`) and an odom TF. Then
`ros2 launch launch/mapping.launch.py lidar:=false odom:=none use_sim_time:=true`
and `ros2 bag play <bag> --clock` (add `cloud_topic:=<topic>` if the bag uses another name).

CPU during a trial: `python3 scripts/cpu_logger.py --trial-id E1-001`, Ctrl+C at the end,
the printed `cpu_avg` goes into trials.csv (or `cpu_avg_from_csv()` from a mission script).

## CHECK on Wednesday

- Jetson IP on the LiDAR network, LiDAR IP (`host_ip:=`, `lidar_ip:=`).
- LiDAR position on the body (static TF numbers) and whether it is mounted tilted or upside down (roll/pitch).
- Box test: a box on the robot's left appears on the left in Foxglove.
- No scan points remain on the body; a box 10 cm from the nose is still in `/scan`.
- base_footprint is at floor level (body height from odom_publisher.py).
