#pragma once

#include <rclcpp/rclcpp.hpp>
#include <nav2_costmap_2d/costmap_2d.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>

namespace everybot_theta_star_planner {
    class ValidGoalSelector {
    public:
        explicit ValidGoalSelector(const rclcpp::Logger &logger, nav2_costmap_2d::Costmap2D *costmap, double search_distance = 0.5);

        bool search_valid_goal(geometry_msgs::msg::Point &lowest_cost_point, geometry_msgs::msg::PoseStamped g);

        void set_search_distance(double search_distance) { search_distance_ = search_distance; }

    private:
        bool find_nearest_non_obstacle_cell(unsigned int& result, unsigned int start);
        std::vector<unsigned int> nhood4(unsigned int idx);
        std::vector<unsigned int> nhood8(unsigned int idx);

        rclcpp::Logger logger_;
        nav2_costmap_2d::Costmap2D *costmap_;
        double search_distance_;
    };
} // everybot_theta_star_planner
