// Copyright 2020 Anshumaan Singh
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#ifndef EVERYBOT_PATH_PLANNER__PATH_PLANNER_HPP_
#define EVERYBOT_PATH_PLANNER__PATH_PLANNER_HPP_

#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <memory>
#include <nav2_core/global_planner.hpp>
#include <nav2_costmap_2d/cost_values.hpp>
#include <nav2_costmap_2d/costmap_2d_ros.hpp>
#include <nav2_util/geometry_utils.hpp>
#include <nav2_util/lifecycle_node.hpp>
#include <nav2_util/node_utils.hpp>
#include <nav2_util/robot_utils.hpp>
#include <nav_msgs/msg/path.hpp>
#include <queue>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <std_msgs/msg/float64_multi_array.hpp>
#include <std_msgs/msg/int8.hpp>
#include <string>
#include <vector>

#include "everybot_path_planner/theta_star.hpp"

using rcl_interfaces::msg::ParameterType;

namespace everybot_path_planner
{

class PathPlanner : public nav2_core::GlobalPlanner
{
   public:
    void configure(
        const rclcpp_lifecycle::LifecycleNode::WeakPtr& parent,
        std::string name,
        std::shared_ptr<tf2_ros::Buffer> tf,
        std::shared_ptr<nav2_costmap_2d::Costmap2DROS> costmap_ros) override;

    void cleanup() override;

    void activate() override;

    void deactivate() override;

    nav_msgs::msg::Path createPlan(
        const geometry_msgs::msg::PoseStamped& start,
        const geometry_msgs::msg::PoseStamped& goal) override;

   protected:
    std::shared_ptr<tf2_ros::Buffer> tf_;
    rclcpp::Clock::SharedPtr clock_;
    rclcpp::Logger logger_{rclcpp::get_logger("everybot_path_planner")};
    std::string global_frame_, name_;
    bool use_final_approach_orientation_;

    // [nav_tuning] strict-vs-lenient plan selection: when max_traversable_cost < 252 and detour_ratio > 0,
    // also plan with the original (lenient) rule and keep the strict path only if it is at most
    // detour_ratio times longer; otherwise fall back to the lenient path (e.g. a person briefly in a corridor).
    double detour_ratio_ = 0.0;

    int collision_timeout_max_ms_;
    int plan_timeout_min_ms_;

    std::vector<std::pair<double, double>> offset_arr = {
        {0.1, 0.0},   // north
        {-0.1, 0.0},  // south
        {0.0, 0.1},   // east
        {0.0, -0.1},  // west

        {0.3, 0.0},   // north
        {-0.3, 0.0},  // south
        {0.0, 0.3},   // east
        {0.0, -0.3},  // west

        {0.5, 0.0},   // north
        {-0.5, 0.0},  // south
        {0.0, 0.5},   // east
        {0.0, -0.5},  // west

        {0.7, 0.0},   // north
        {-0.7, 0.0},  // south
        {0.0, 0.7},   // east
        {0.0, -0.7},  // west

        {1.0, 0.0},   // north
        {-1.0, 0.0},  // south
        {0.0, 1.0},   // east
        {0.0, -1.0},  // west
    };

    // parent node weak ptr
    rclcpp_lifecycle::LifecycleNode::WeakPtr parent_node_;

    std::unique_ptr<theta_star::ThetaStar> planner_;

    // Dynamic parameters handler
    rclcpp::node_interfaces::OnSetParametersCallbackHandle::SharedPtr dyn_params_handler_;

    /**
     * @brief the function responsible for calling the algorithm and retrieving a
     * path from it
     * @return global_path is the planned path to be taken
     */
    bool getPlan(nav_msgs::msg::Path& global_path);

    /**
     * @brief interpolates points between the consecutive waypoints of the path
     * @param raw_path is used to send in the path received from the planner
     * @param dist_bw_points is used to send in the interpolation_resolution
     * (which has been set as the costmap resolution)
     * @return the final path with waypoints at a distance of the value of
     * interpolation_resolution of each other
     */
    static nav_msgs::msg::Path linearInterpolation(const std::vector<coordsW>& raw_path, const double& dist_bw_points);

    /**
     * @brief Callback executed when a paramter change is detected
     * @param parameters list of changed parameters
     */
    rcl_interfaces::msg::SetParametersResult dynamicParametersCallback(std::vector<rclcpp::Parameter> parameters);

    std::pair<double, double> offsetDistance(double x, double y, int offset_num);

    int getOccupancyValue(double x, double y);

    void subsStaticMap();

    bool pathCheck(nav_msgs::msg::Path global_path);

    rclcpp::Publisher<std_msgs::msg::Int8>::SharedPtr dest_publisher_;
    rclcpp::Publisher<std_msgs::msg::Float64MultiArray>::SharedPtr dest_coord_publisher_;

    // 충돌 해결을 위한 검사 로직 추가
    rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr collsion_subs_;
    rclcpp::Subscription<nav_msgs::msg::OccupancyGrid>::SharedPtr static_map_subs_;
    rclcpp::Subscription<nav_msgs::msg::Path>::SharedPtr plan_subs_;
    std::chrono::steady_clock::time_point collision_time_;
    std::chrono::steady_clock::time_point plan_time_;
    nav_msgs::msg::OccupancyGrid::SharedPtr static_map_;
    uint8_t static_map_checker_;

    std::chrono::steady_clock::time_point plan_error_log_time_;
    std::chrono::steady_clock::time_point plan_error_log_time2_;
    std::chrono::steady_clock::time_point static_map_log_time_;
};
}  // namespace everybot_path_planner

#endif  //  EVERYBOT_PATH_PLANNER__THETA_STAR_PLANNER_HPP_
