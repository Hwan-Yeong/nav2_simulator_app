#include "everybot_theta_star_planner/valid_goal_selector.hpp"

#include <nav2_costmap_2d/cost_values.hpp>

#include "everybot_theta_star_planner/logger.hpp"

namespace everybot_theta_star_planner {
    ValidGoalSelector::ValidGoalSelector(
        const rclcpp::Logger &logger,
        nav2_costmap_2d::Costmap2D *costmap,
        double search_distance): logger_(logger), costmap_(costmap), search_distance_(search_distance) {
    }

    bool ValidGoalSelector::search_valid_goal(geometry_msgs::msg::Point &lowest_cost_point, geometry_msgs::msg::PoseStamped goal) {
        double robot_x = goal.pose.position.x;
        double robot_y = goal.pose.position.y;
        unsigned int mx, my;

        if (!costmap_->worldToMap(robot_x, robot_y, mx, my)) {
            RCLCPP_ERROR(logger_, "goal is out of costmap bounds");
            return false;
        }

        if (search_distance_ <= 0) {
            RCLCPP_ERROR(logger_, "Invalid search distance: %f", search_distance_);
            return false;
        }

        std::lock_guard lock(*costmap_->getMutex());

        unsigned int idx, pos = costmap_->getIndex(mx, my);
        if (find_nearest_non_obstacle_cell(idx, pos)) {
            costmap_->indexToCells(idx, mx, my);
        }

        double resolution = costmap_->getResolution();
        int cell_range = static_cast<int>(search_distance_ / resolution);
        unsigned int width = costmap_->getSizeInCellsX();
        unsigned int height = costmap_->getSizeInCellsY();

        int min_cost = std::numeric_limits<int>::max();
        unsigned int best_mx = mx, best_my = my;
        double min_distance = std::numeric_limits<double>::max();

        for (int dx = -cell_range; dx <= cell_range; ++dx) {
            for (int dy = -cell_range; dy <= cell_range; ++dy) {
                unsigned int nx = mx + dx;
                unsigned int ny = my + dy;

                // check node is out of costmap or on obstacle cell
                if (nx >= width || ny >= height) {
                    continue;
                }
                if (costmap_->getCost(nx, ny) == nav2_costmap_2d::LETHAL_OBSTACLE) {
                    continue;
                }

                int total_cost = 0;
                bool is_out_of_bounds = false;
                for (int ox = -1; ox <= 1; ++ox) {
                    for (int oy = -1; oy <= 1; ++oy) {
                        unsigned int neighbor_x = nx + ox;
                        unsigned int neighbor_y = ny + oy;

                        // check neighbor is out of costmap
                        if (neighbor_x >= width || neighbor_y >= height) {
                            is_out_of_bounds = true;
                            break;
                        }

                        total_cost += costmap_->getCost(neighbor_x, neighbor_y);
                    }
                    if (is_out_of_bounds) break;
                }
                if (is_out_of_bounds) continue;

                double distance = std::hypot(nx - mx, ny - my);
                if (total_cost < min_cost || (total_cost == min_cost && distance < min_distance)) {
                    min_cost = total_cost;
                    min_distance = distance;
                    best_mx = nx;
                    best_my = ny;
                }
            }
        }

        if (costmap_->getCost(best_mx, best_my) == nav2_costmap_2d::LETHAL_OBSTACLE) {
            RCL_LOG_WARN(logger_, "Selected escape point is in an obstacle. No valid escape found.");
            return false;
        }

        double best_x, best_y;
        costmap_->mapToWorld(best_mx, best_my, best_x, best_y);
        lowest_cost_point.x = best_x;
        lowest_cost_point.y = best_y;
        lowest_cost_point.z = 0.0;

        return true;
    }

    std::vector<unsigned int> ValidGoalSelector::nhood4(unsigned int idx) {
        // get 4-connected neighbourhood indexes, check for edge of map
        std::vector<unsigned int> out;

        unsigned int size_x_ = costmap_->getSizeInCellsX(),
                     size_y_ = costmap_->getSizeInCellsY();

        if (idx > size_x_ * size_y_ - 1) {
            return out;
        }

        if (idx % size_x_ > 0) {
            out.push_back(idx - 1);
        }
        if (idx % size_x_ < size_x_ - 1) {
            out.push_back(idx + 1);
        }
        if (idx >= size_x_) {
            out.push_back(idx - size_x_);
        }
        if (idx < size_x_ * (size_y_ - 1)) {
            out.push_back(idx + size_x_);
        }
        return out;
    }


    std::vector<unsigned int> ValidGoalSelector::nhood8(unsigned int idx) {
        // get 8-connected neighbourhood indexes, check for edge of map
        std::vector<unsigned int> out = nhood4(idx);

        unsigned int size_x_ = costmap_->getSizeInCellsX(),
                     size_y_ = costmap_->getSizeInCellsY();

        if (idx > size_x_ * size_y_ - 1) {
            return out;
        }

        if (idx % size_x_ > 0 && idx >= size_x_) {
            out.push_back(idx - 1 - size_x_);
        }
        if (idx % size_x_ > 0 && idx < size_x_ * (size_y_ - 1)) {
            out.push_back(idx - 1 + size_x_);
        }
        if (idx % size_x_ < size_x_ - 1 && idx >= size_x_) {
            out.push_back(idx + 1 - size_x_);
        }
        if (idx % size_x_ < size_x_ - 1 && idx < size_x_ * (size_y_ - 1)) {
            out.push_back(idx + 1 + size_x_);
        }

        return out;
    }

    bool ValidGoalSelector::find_nearest_non_obstacle_cell(unsigned int &result, unsigned int start) {
        const unsigned char* map = costmap_->getCharMap();
        const unsigned int size_x = costmap_->getSizeInCellsX(),
                           size_y = costmap_->getSizeInCellsY();

        if (start >= size_x * size_y) {
            return false;
        }

        // initialize breadth first search
        std::queue<unsigned int> bfs;
        std::vector<bool> visited_flag(size_x * size_y, false);

        // push initial cell
        bfs.push(start);
        visited_flag[start] = true;

        // search for neighbouring cell matching value
        while (!bfs.empty()) {
            unsigned int idx = bfs.front();
            bfs.pop();

            // return if cell of correct value is found
            if (map[idx] <= nav2_costmap_2d::MAX_NON_OBSTACLE) {
                result = idx;
                return true;
            }

            // iterate over all adjacent unvisited cells
            for (unsigned nbr : nhood8(idx)) {
                if (!visited_flag[nbr]) {
                    bfs.push(nbr);
                    visited_flag[nbr] = true;
                }
            }
        }

        return false;
    }

} // everybot_theta_star_planner
