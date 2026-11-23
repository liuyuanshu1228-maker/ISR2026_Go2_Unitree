"""Named places for the Go2 (research notes #4).

Each place in locations.yaml has:
  - a goal pose (x, y, yaw): where the robot stops for go_to("<name>")
  - a radius: the robot counts as "at" the place within this distance

Plain Python (no ROS), so it runs and tests on a Mac.
"""

import math
from pathlib import Path

import yaml

LOCATIONS_FILE = Path(__file__).with_name("locations.yaml")


def load_places(path=LOCATIONS_FILE):
    """Read the places from the YAML file into a dict: name -> settings."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return data["places"]


PLACES = load_places()


def get_pose(name, places=None):
    """Return (x, y, yaw) of a place, e.g. get_pose("lift") -> (5.0, 0.0, 0.0)."""
    places = PLACES if places is None else places
    if name not in places:
        known = ", ".join(places)
        raise KeyError(f"Unknown place '{name}'. Known places: {known}")
    p = places[name]
    return p["x"], p["y"], p.get("yaw", 0.0)


def where_am_i(x, y, places=None):
    """Return the name of the place the robot is at, or 'unknown'.

    The robot is "at" a place when its straight-line distance to the place
    is at most the place's radius. If two places overlap, the closest wins.
    """
    places = PLACES if places is None else places
    best_name, best_dist = "unknown", math.inf
    for name, p in places.items():
        dist = math.hypot(x - p["x"], y - p["y"])  # = sqrt(dx**2 + dy**2)
        if dist <= p["radius"] and dist < best_dist:
            best_name, best_dist = name, dist
    return best_name
