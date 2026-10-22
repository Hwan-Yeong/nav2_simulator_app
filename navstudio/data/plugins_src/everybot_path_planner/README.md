# everybot_path_planner

Everybot global path planner for Nav2. It extends the Nav2 Theta* planner with
alternative-destination handling and optional limits on how close a path may pass to obstacles.

## Published topic

| Topic | Type | Value |
|---|---|---|
| `/path_planning/destination` | `std_msgs/msg/UInt8` | 0 original destination · 1 alternative destination · 2 no path |

## Parameters

```yaml
planner_server:
  ros__parameters:
    planner_plugins: ["GridBased"]
    GridBased:
      plugin: "everybot_path_planner/PathPlanner"
      allow_unknown: false
      how_many_corners: 8          # keep at 8
      w_euc_cost: 1.0
      w_traversal_cost: 8.0        # higher: prefer paths farther from obstacles
      w_heuristic_cost: 1.0
      max_traversable_cost: 252    # optional; 252 = only inscribed/lethal cells are blocked
      relax_radius: 0.35           # cells this close to start/goal ignore max_traversable_cost
      detour_ratio: 0.0            # optional; >0 keeps the original path when the strict one is this much longer
```
