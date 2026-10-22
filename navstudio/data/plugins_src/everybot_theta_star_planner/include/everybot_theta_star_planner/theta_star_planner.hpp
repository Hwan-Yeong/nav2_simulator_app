#pragma once

#include <iostream>
#include <cmath>
#include <string>
#include <chrono>
#include <queue>
#include <algorithm>
#include <memory>
#include <vector>
#include "rclcpp/rclcpp.hpp"
#include "nav2_core/global_planner.hpp"
#include "nav_msgs/msg/path.hpp"
#include "nav2_util/robot_utils.hpp"
#include "nav2_util/lifecycle_node.hpp"
#include "nav2_costmap_2d/costmap_2d_ros.hpp"
#include "nav2_costmap_2d/cost_values.hpp"
#include "nav2_util/node_utils.hpp"
#include "nav2_util/geometry_utils.hpp"

#include "nav2_theta_star_planner/theta_star.hpp"
#include "everybot_theta_star_planner/valid_goal_selector.hpp"

using rcl_interfaces::msg::ParameterType;

namespace everybot_theta_star_planner {
    class ThetaStarPlanner : public nav2_core::GlobalPlanner {
    public:
        void configure(
            const rclcpp_lifecycle::LifecycleNode::WeakPtr &parent,
            std::string name, std::shared_ptr<tf2_ros::Buffer> tf,
            std::shared_ptr<nav2_costmap_2d::Costmap2DROS> costmap_ros) override;

        void cleanup() override;

        void activate() override;

        void deactivate() override;

        nav_msgs::msg::Path createPlan(
            const geometry_msgs::msg::PoseStamped &start,
            const geometry_msgs::msg::PoseStamped &goal) override;

    protected:
        std::shared_ptr<ValidGoalSelector> goal_selector_;
        std::shared_ptr<tf2_ros::Buffer> tf_;
        rclcpp::Clock::SharedPtr clock_;
        rclcpp::Logger logger_{rclcpp::get_logger("everybot_theta_star_planner")};
        std::string global_frame_, name_;
        double robot_radius_;
        double goal_update_timeout_;
        // double search_distance_padding_;
        bool use_final_approach_orientation_;

        // parent node weak ptr
        rclcpp_lifecycle::LifecycleNode::WeakPtr parent_node_;
        rclcpp_lifecycle::LifecyclePublisher<geometry_msgs::msg::PoseStamped>::SharedPtr goal_update_pub_;

        std::unique_ptr<theta_star::ThetaStar> planner_;

        // Dynamic parameters handler
        rclcpp::node_interfaces::OnSetParametersCallbackHandle::SharedPtr dyn_params_handler_;


        /**
         * @brief the function responsible for calling the algorithm and retrieving a path from it
         * @return global_path is the planned path to be taken
         */
        void getPlan(nav_msgs::msg::Path &global_path);

        bool isValidGoal(unsigned x, unsigned y);

        /**
         * @brief interpolates points between the consecutive waypoints of the path
         * @param raw_path is used to send in the path received from the planner
         * @param dist_bw_points is used to send in the interpolation_resolution (which has been set as the costmap resolution)
         * @return the final path with waypoints at a distance of the value of interpolation_resolution of each other
         */
        static nav_msgs::msg::Path linearInterpolation(
            const std::vector<coordsW> &raw_path,
            const double &dist_bw_points);

        /**
         * @brief Callback executed when a paramter change is detected
         * @param parameters list of changed parameters
         */
        rcl_interfaces::msg::SetParametersResult
        dynamicParametersCallback(std::vector<rclcpp::Parameter> parameters);
    };
} // everybot_theta_star_planner
