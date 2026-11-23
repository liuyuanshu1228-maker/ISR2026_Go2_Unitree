#!/usr/bin/env bash
# check_sensors.sh  -  Go2 iSR 2026   Owner: Yuanshu
#
# Quick health check before every mapping / navigation run (bring-up checklist,
# section 7 of the plan). Checks, in order:
#   1. the LiDAR answers ping
#   2. the topics exist and publish at a sensible rate
#      /livox/lidar, /scan, /sportmodestate, /odom  (+ /map, /amcl_pose if running)
#   3. the TF chain map -> odom -> base_footprint -> base_link -> livox_frame
#
# Usage:
#   scripts/check_sensors.sh                      # everything
#   scripts/check_sensors.sh --lidar-ip 192.168.1.166
#   scripts/check_sensors.sh --skip-ping          # Docker / rosbag, no real LiDAR
#   scripts/check_sensors.sh --dry-run            # print the commands, run nothing
#
# Exit code 0 = all required checks passed, 1 = at least one failed.
# Source ROS first:  source /opt/ros/humble/setup.bash

set -u

LIDAR_IP="192.168.1.166"   # CHECK on Wednesday
TIMEOUT=6                  # seconds per check
DRY_RUN=0
SKIP_PING=0

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  cat <<USAGE
Options:
  --lidar-ip IP   LiDAR address to ping (default $LIDAR_IP)
  --timeout S     seconds to wait per check (default $TIMEOUT)
  --skip-ping     do not ping the LiDAR
  --dry-run       print the commands instead of running them
  -h, --help      show this help
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --lidar-ip) LIDAR_IP="$2"; shift 2 ;;
    --timeout)  TIMEOUT="$2"; shift 2 ;;
    --skip-ping) SKIP_PING=1; shift ;;
    --dry-run)  DRY_RUN=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 2 ;;
  esac
done

PASS=0; FAIL=0; WARN=0
ok()   { echo "  [ OK ] $*"; PASS=$((PASS + 1)); }
bad()  { echo "  [FAIL] $*"; FAIL=$((FAIL + 1)); }
warn() { echo "  [WARN] $*"; WARN=$((WARN + 1)); }

if [ "$DRY_RUN" -eq 0 ] && ! command -v ros2 >/dev/null 2>&1; then
  echo "ros2 not found. Run: source /opt/ros/humble/setup.bash"
  exit 1
fi

# ---- 1. LiDAR on the network -------------------------------------------------
echo "1. LiDAR network"
if [ "$SKIP_PING" -eq 1 ]; then
  warn "ping skipped (--skip-ping)"
elif [ "$DRY_RUN" -eq 1 ]; then
  echo "  would run: ping -c 2 -W 1 $LIDAR_IP"
elif ping -c 2 -W 1 "$LIDAR_IP" >/dev/null 2>&1; then
  ok "LiDAR $LIDAR_IP answers ping"
else
  bad "LiDAR $LIDAR_IP does not answer (cable, power, IP? host must be on 192.168.1.x)"
fi

# ---- 2. Topics -----------------------------------------------------------------
# topic  min_hz  required(1)/optional(0)  hint
TOPICS=(
  "/livox/lidar     5  1  Livox driver running? xfer_format must be 0 (PointCloud2)"
  "/scan            5  1  pointcloud_to_laserscan + box filter running? TF base_footprint -> livox_frame?"
  "/sportmodestate  10 1  unitree_ros2 sourced? same ROS_DOMAIN_ID / CycloneDDS as the robot?"
  "/odom            10 1  odom_publisher.py running?"
  "/map             0  0  only while slam_toolbox or map_server runs"
  "/amcl_pose       0  0  only while AMCL runs (navigation)"
)

topic_hz() {  # prints the average rate of a topic, empty if none
  timeout "$TIMEOUT" ros2 topic hz "$1" 2>/dev/null | awk '/average rate/ {r=$3} END {print r}'
}

echo "2. Topics"
if [ "$DRY_RUN" -eq 1 ]; then
  for line in "${TOPICS[@]}"; do
    read -r topic _ _ _ <<<"$line"
    echo "  would run: timeout $TIMEOUT ros2 topic hz $topic"
  done
else
  LIST="$(timeout "$TIMEOUT" ros2 topic list 2>/dev/null)"
  for line in "${TOPICS[@]}"; do
    read -r topic min_hz required hint <<<"$line"
    if ! grep -qx "$topic" <<<"$LIST"; then
      if [ "$required" -eq 1 ]; then bad "$topic missing. $hint"; else warn "$topic not published ($hint)"; fi
      continue
    fi
    if [ "$min_hz" -eq 0 ]; then
      ok "$topic exists"   # /map and /amcl_pose publish rarely, don't measure
      continue
    fi
    hz="$(topic_hz "$topic")"
    if [ -z "$hz" ]; then
      if [ "$required" -eq 1 ]; then bad "$topic exists but no messages in ${TIMEOUT}s. $hint"; else warn "$topic silent"; fi
    elif awk -v h="$hz" -v m="$min_hz" 'BEGIN {exit !(h >= m)}'; then
      ok "$topic at ${hz} Hz"
    else
      bad "$topic only ${hz} Hz (expected >= $min_hz Hz)"
    fi
  done
fi

# ---- 3. TF chain -----------------------------------------------------------------
# parent child required
TFS=(
  "base_link       livox_frame     1"
  "base_footprint  base_link       1"
  "odom            base_footprint  1"
  "map             odom            0"
)

echo "3. TF chain (map -> odom -> base_footprint -> base_link -> livox_frame)"
for line in "${TFS[@]}"; do
  read -r parent child required <<<"$line"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  would run: timeout $TIMEOUT ros2 run tf2_ros tf2_echo $parent $child"
    continue
  fi
  out="$(timeout "$TIMEOUT" ros2 run tf2_ros tf2_echo "$parent" "$child" 2>&1)"
  if grep -q "Translation" <<<"$out"; then
    xyz="$(grep -m1 "Translation" <<<"$out" | sed 's/.*Translation: //')"
    ok "$parent -> $child  $xyz"
  elif [ "$required" -eq 1 ]; then
    bad "$parent -> $child missing"
  else
    warn "$parent -> $child missing (only while slam_toolbox or AMCL runs)"
  fi
done

echo
echo "Result: $PASS ok, $WARN warnings, $FAIL failed"
[ "$DRY_RUN" -eq 1 ] && echo "(dry run: nothing was checked)"
[ "$FAIL" -eq 0 ]
