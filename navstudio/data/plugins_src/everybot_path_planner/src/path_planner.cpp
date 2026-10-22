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

#include "everybot_path_planner/path_planner.hpp"
#include <memory>
#include <string>
#include <vector>
#include "everybot_path_planner/theta_star.hpp"

namespace everybot_path_planner
{
void PathPlanner::configure(
    const rclcpp_lifecycle::LifecycleNode::WeakPtr& parent,
    std::string name,
    std::shared_ptr<tf2_ros::Buffer> tf,
    std::shared_ptr<nav2_costmap_2d::Costmap2DROS> costmap_ros)
{
    planner_ = std::make_unique<theta_star::ThetaStar>();
    parent_node_ = parent;
    auto node = parent_node_.lock();
    logger_ = node->get_logger();
    clock_ = node->get_clock();
    name_ = name;
    tf_ = tf;
    planner_->costmap_ = costmap_ros->getCostmap();
    global_frame_ = costmap_ros->getGlobalFrameID();
    RCLCPP_INFO(logger_, "everybot_path_planner start !");

    nav2_util::declare_parameter_if_not_declared(node, name_ + ".how_many_corners", rclcpp::ParameterValue(8));

    node->get_parameter(name_ + ".how_many_corners", planner_->how_many_corners_);

    if (planner_->how_many_corners_ != 8 && planner_->how_many_corners_ != 4)
    {
        planner_->how_many_corners_ = 8;
        RCLCPP_WARN(
            logger_,
            "Your value for - .how_many_corners  was overridden, "
            "and is now set to 8");
    }

    nav2_util::declare_parameter_if_not_declared(node, name_ + ".allow_unknown", rclcpp::ParameterValue(true));
    node->get_parameter(name_ + ".allow_unknown", planner_->allow_unknown_);

    nav2_util::declare_parameter_if_not_declared(node, name_ + ".w_euc_cost", rclcpp::ParameterValue(1.0));
    node->get_parameter(name_ + ".w_euc_cost", planner_->w_euc_cost_);

    nav2_util::declare_parameter_if_not_declared(node, name_ + ".w_traversal_cost", rclcpp::ParameterValue(2.0));
    node->get_parameter(name_ + ".w_traversal_cost", planner_->w_traversal_cost_);

    planner_->w_heuristic_cost_ = planner_->w_euc_cost_ < 1.0 ? planner_->w_euc_cost_ : 1.0;

    // [nav_tuning] keep plans out of near-inscribed gaps (default 252 = original behaviour)
    nav2_util::declare_parameter_if_not_declared(node, name_ + ".max_traversable_cost", rclcpp::ParameterValue(252));
    node->get_parameter(name_ + ".max_traversable_cost", planner_->max_traversable_cost_);
    double relax_radius = 0.35;
    nav2_util::declare_parameter_if_not_declared(node, name_ + ".relax_radius", rclcpp::ParameterValue(0.35));
    node->get_parameter(name_ + ".relax_radius", relax_radius);
    planner_->relax_radius_cells_ = static_cast<int>(std::ceil(relax_radius / planner_->costmap_->getResolution()));
    nav2_util::declare_parameter_if_not_declared(node, name_ + ".detour_ratio", rclcpp::ParameterValue(0.0));
    node->get_parameter(name_ + ".detour_ratio", detour_ratio_);

    nav2_util::declare_parameter_if_not_declared(
        node, name + ".use_final_approach_orientation", rclcpp::ParameterValue(false));
    node->get_parameter(name + ".use_final_approach_orientation", use_final_approach_orientation_);

    // collision timeout settings
    nav2_util::declare_parameter_if_not_declared(
        node, name_ + ".collision_timeout_max_ms", rclcpp::ParameterValue(8000));
    node->get_parameter(name_ + ".collision_timeout_max_ms", collision_timeout_max_ms_);

    nav2_util::declare_parameter_if_not_declared(node, name_ + ".plan_timeout_min_ms", rclcpp::ParameterValue(4000));
    node->get_parameter(name_ + ".plan_timeout_min_ms", plan_timeout_min_ms_);

    dest_publisher_ = node->create_publisher<std_msgs::msg::Int8>("/path_planning/destination", 1);
    dest_coord_publisher_ = node->create_publisher<std_msgs::msg::Float64MultiArray>("/path_planning/coordiante", 1);

    rclcpp::QoS qos_profile(rclcpp::KeepLast(1));
    qos_profile.best_effort();

    collsion_subs_ = node->create_subscription<sensor_msgs::msg::PointCloud2>(
        "/sensor_to_pointcloud/collision",
        qos_profile,
        [this](const sensor_msgs::msg::PointCloud2::SharedPtr msg)
        {
            if ((msg->width * msg->height) > 0 && !msg->data.empty())
            {
                collision_time_ = std::chrono::steady_clock::now();
            }
        });

    plan_subs_ = node->create_subscription<nav_msgs::msg::Path>(
        "/plan",
        10,
        [this](const nav_msgs::msg::Path::SharedPtr msg)
        {
            (void)msg;
            plan_time_ = std::chrono::steady_clock::now();
        });
    subsStaticMap();
}

void PathPlanner::subsStaticMap()
{
    if (static_map_subs_)
    {
        static_map_subs_.reset();
    }

    rclcpp::QoS qos_profile(rclcpp::KeepLast(1));
    qos_profile.best_effort();
    auto node = parent_node_.lock();
    static_map_subs_ = node->create_subscription<nav_msgs::msg::OccupancyGrid>(
        "/map", qos_profile, [this](const nav_msgs::msg::OccupancyGrid::SharedPtr msg) { static_map_ = msg; });
}

void PathPlanner::cleanup()
{
    // RCLCPP_INFO(logger_, "CleaningUp plugin %s of type everybot_path_planner", name_.c_str());
    planner_.reset();
}

void PathPlanner::activate()
{
    // RCLCPP_INFO(logger_, "Activating plugin %s of type everybot_path_planner", name_.c_str());
    // Add callback for dynamic parameters
    auto node = parent_node_.lock();
    dyn_params_handler_ = node->add_on_set_parameters_callback(
        std::bind(&PathPlanner::dynamicParametersCallback, this, std::placeholders::_1));
}

void PathPlanner::deactivate()
{
    // RCLCPP_INFO(logger_, "Deactivating plugin %s of type everybot_path_planner", name_.c_str());
}

bool PathPlanner::pathCheck(nav_msgs::msg::Path global_path)
{
    bool isValid = true;
    // 경로 검사 진행
    for (size_t i = 0; i < global_path.poses.size(); i++)
    {
        auto pose = global_path.poses[i];
        auto position = pose.pose.position;
        int path_static_cost = getOccupancyValue(position.x, position.y);
        if (path_static_cost == -1)
        {
            RCLCPP_INFO(logger_, "The path has unknown value. coordinate: %.2f,%2.f", position.x, position.y);
            isValid = false;
            break;
        }
    }
    return isValid;
}

nav_msgs::msg::Path PathPlanner::createPlan(
    const geometry_msgs::msg::PoseStamped& start,
    const geometry_msgs::msg::PoseStamped& goal)
{
    nav_msgs::msg::Path global_path;
    auto start_time = std::chrono::steady_clock::now();

    std::unique_lock<nav2_costmap_2d::Costmap2D::mutex_t> lock(*(planner_->costmap_->getMutex()));

    unsigned int mx_start, my_start, mx_goal, my_goal;

    // 시작 위치 유효성 확인
    if (!planner_->costmap_->worldToMap(start.pose.position.x, start.pose.position.y, mx_start, my_start))
    {
        // RCLCPP_WARN(logger_, "Start Coordinates were outside map bounds");
        return global_path;
    }

    // 목표 위치 유효성 확인
    if (!planner_->costmap_->worldToMap(goal.pose.position.x, goal.pose.position.y, mx_goal, my_goal))
    {
        // RCLCPP_WARN(logger_, "Goal Coordinates were outside map bounds");
        return global_path;
    }

    // 목표 위치가 장애물 위에 있는 경우 처리
    unsigned char goal_cost = planner_->costmap_->getCost(mx_goal, my_goal);
    // static map 데이터 확인
    int static_cost = getOccupancyValue(goal.pose.position.x, goal.pose.position.y);
    if (static_cost == -2)
    {
        RCLCPP_INFO(
            logger_,
            "The target destination(%f,%f) cost value is %d",
            goal.pose.position.x,
            goal.pose.position.y,
            goal_cost);
    }
    else
    {
        RCLCPP_INFO(
            logger_,
            "The target destination(%f,%f) cost value is %d, static value is %d",
            goal.pose.position.x,
            goal.pose.position.y,
            goal_cost,
            static_cost);
    }

    if (static_cost == -2 && static_map_checker_ < 100)
    {
        if (std::chrono::duration_cast<std::chrono::milliseconds>(start_time - static_map_log_time_).count() > 10000)
        {
            static_map_log_time_ = start_time;
            RCLCPP_WARN(
                logger_, "Static map is not loaded(-2). reset /map topic subscriber (%d).", static_map_checker_);
        }
        static_map_checker_++;
        subsStaticMap();
        if (static_map_checker_ < 3)
            return global_path;
    }
    else if (static_map_checker_ == 100)
    {
        static_map_checker_++;
        RCLCPP_WARN(logger_, "Static map is not loaded(-2). retry counts is over(100) .");
    }

    // cost value 255->250
    // if (goal_cost >= 250)
    int limit_value = 150;
    bool isValidPath = false;
    if (!(goal_cost > limit_value || static_cost == -1))
    {
        planner_->setStartAndGoal(start, goal);
        bool is_collision_reulst = getPlan(global_path);
        if (global_path.poses.size() > 0)
        {
            isValidPath = pathCheck(global_path);
        }
        if (isValidPath)
        {
            std_msgs::msg::Int8 path_type_msg;
            path_type_msg.data = 0;

            std_msgs::msg::Float64MultiArray goal_msg;
            goal_msg.data = {goal.pose.position.x, goal.pose.position.y};

            if (is_collision_reulst)
            {
                path_type_msg.data = 1;
                goal_msg.data = {start.pose.position.x, start.pose.position.y};
            }

            dest_publisher_->publish(path_type_msg);
            dest_coord_publisher_->publish(goal_msg);
            RCLCPP_INFO(
                logger_, "Create path to original destination (%f,%f).", goal.pose.position.x, goal.pose.position.y);
        }
        else
        {
            RCLCPP_WARN(
                logger_,
                "Invalid path to the original destination (%f,%f). find alternative destination.",
                goal.pose.position.x,
                goal.pose.position.y);
        }
    }

    if ((goal_cost > limit_value || static_cost == -1) || !isValidPath)
    {
        geometry_msgs::msg::PoseStamped adjusted_goal = goal;
        bool isFindPath = false;
        for (long unsigned int i = 0; i < offset_arr.size(); i++)
        {
            auto newCoordinate = offsetDistance(goal.pose.position.x, goal.pose.position.y, i);

            planner_->costmap_->worldToMap(newCoordinate.first, newCoordinate.second, mx_goal, my_goal);
            goal_cost = planner_->costmap_->getCost(mx_goal, my_goal);
            static_cost = getOccupancyValue(newCoordinate.first, newCoordinate.second);
            // if (static_cost == -1 || static_cost == -3)
            // {
            //     RCLCPP_INFO(
            //         logger_,
            //         "The alternative destination(%f,%f) static value is %d(%s). Skip.",
            //         newCoordinate.first,
            //         newCoordinate.second,
            //         static_cost,
            //         static_cost == -1 ? "unknown" : "out of map");
            //     continue;
            // }

            // 재조정된 목표가 맵 범위 내인지 확인
            if (!planner_->costmap_->worldToMap(newCoordinate.first, newCoordinate.second, mx_goal, my_goal) ||
                planner_->costmap_->getCost(mx_goal, my_goal) > limit_value || static_cost == -1)
            // planner_->costmap_->getCost(mx_goal, my_goal) == nav2_costmap_2d::LETHAL_OBSTACLE)
            {
                continue;
            }
            else
            {
                // RCLCPP_INFO(logger_,"isFindPath = true");
                adjusted_goal.pose.position.x = newCoordinate.first;
                adjusted_goal.pose.position.y = newCoordinate.second;
                planner_->setStartAndGoal(start, adjusted_goal);
                getPlan(global_path);
                if (global_path.poses.size() > 0)
                {
                    isFindPath = pathCheck(global_path);
                    if (isFindPath)
                        break;
                }
            }
        }
        // 조정된 목표를 사용하도록 설정
        if (isFindPath)
        {
            planner_->setStartAndGoal(start, adjusted_goal);
            getPlan(global_path);

            // 0: orignal dest
            // 1: alternative dest
            // 2: cannot create path
            std_msgs::msg::Int8 path_type_msg;
            path_type_msg.data = 1;

            std_msgs::msg::Float64MultiArray goal_msg;
            goal_msg.data = {adjusted_goal.pose.position.x, adjusted_goal.pose.position.y};

            dest_publisher_->publish(path_type_msg);
            dest_coord_publisher_->publish(goal_msg);

            RCLCPP_INFO(
                logger_,
                "Create path to alternative destination (%f,%f).",
                adjusted_goal.pose.position.x,
                adjusted_goal.pose.position.y);
        }
        else
        {
            std_msgs::msg::Int8 path_type_msg;
            path_type_msg.data = 2;
            dest_publisher_->publish(path_type_msg);

            RCLCPP_INFO(
                logger_, "Cannot create path to destination (%f, %f).", goal.pose.position.x, goal.pose.position.y);
            return global_path;
        }
    }
    size_t plan_size = global_path.poses.size();
    if (plan_size > 0)
    {
        global_path.poses.back().pose.orientation = goal.pose.orientation;
    }

    if (use_final_approach_orientation_)
    {
        if (plan_size == 1)
        {
            global_path.poses.back().pose.orientation = start.pose.orientation;
        }
        else if (plan_size > 1)
        {
            double dx, dy, theta;
            auto last_pose = global_path.poses.back().pose.position;
            auto approach_pose = global_path.poses[plan_size - 2].pose.position;
            dx = last_pose.x - approach_pose.x;
            dy = last_pose.y - approach_pose.y;
            theta = atan2(dy, dx);
            global_path.poses.back().pose.orientation = nav2_util::geometry_utils::orientationAroundZAxis(theta);
        }
    }

    auto stop_time = std::chrono::steady_clock::now();
    auto dur = std::chrono::duration_cast<std::chrono::microseconds>(stop_time - start_time);
    RCLCPP_DEBUG(logger_, "the time taken is : %i", static_cast<int>(dur.count()));
    RCLCPP_DEBUG(logger_, "the nodes_opened are:  %i", planner_->nodes_opened);
    return global_path;
}

std::pair<double, double> PathPlanner::offsetDistance(double x, double y, int offset_num)
{
    double newx = x;
    double newy = y;
    return {newx + offset_arr[offset_num].first, newy + offset_arr[offset_num].second};
}

int PathPlanner::getOccupancyValue(double x, double y)
{
    auto map_ = static_map_;
    if (!map_)
    {
        return -2;
    }

    auto width = map_->info.width;
    auto height = map_->info.height;
    auto resolution = map_->info.resolution;
    auto origin = map_->info.origin;

    int mx = static_cast<int>((x - origin.position.x) / resolution);
    int my = static_cast<int>((y - origin.position.y) / resolution);
    int index = my * map_->info.width + mx;
    if (mx >= 0 && mx < static_cast<int>(width) && my >= 0 && my < static_cast<int>(height))
    {
        return map_->data[index];  // 0: free, 100: occupied, -1: unknown
    }
    // RCLCPP_ERROR(logger_, "Goal Coordinate out of map bounds");
    return -3;
}

bool PathPlanner::getPlan(nav_msgs::msg::Path& global_path)
{
    bool is_collision = false;
    std::vector<coordsW> path;
    auto start_time = std::chrono::steady_clock::now();
    if (planner_->isUnsafeToPlan())
    {
        if (std::chrono::duration_cast<std::chrono::milliseconds>(start_time - plan_error_log_time_).count() > 1000)
        {
            plan_error_log_time_ = start_time;
            RCLCPP_ERROR(logger_, "Either of the start or goal pose are an obstacle! ");
        }
        global_path.poses.clear();
    }
    else if ([&]() {
                 const bool strict_ok = planner_->generatePath(path);
                 if (planner_->max_traversable_cost_ >= 252 || detour_ratio_ <= 0.0)
                 {
                     return strict_ok;
                 }
                 std::vector<coordsW> lenient;
                 const int saved = planner_->max_traversable_cost_;
                 planner_->max_traversable_cost_ = 252;
                 const bool lenient_ok = planner_->generatePath(lenient);
                 planner_->max_traversable_cost_ = saved;
                 auto length = [](const std::vector<coordsW>& p) {
                     double l = 0.0;
                     for (size_t i = 1; i < p.size(); i++)
                     {
                         l += std::hypot(p[i].x - p[i - 1].x, p[i].y - p[i - 1].y);
                     }
                     return l;
                 };
                 if (lenient_ok && (!strict_ok || length(path) > detour_ratio_ * length(lenient)))
                 {
                     path = lenient;
                     return true;
                 }
                 return strict_ok;
             }())
    {
        global_path = linearInterpolation(path, planner_->costmap_->getResolution());
    }
    else
    {
        auto c_time_diff_ms =
            std::chrono::duration_cast<std::chrono::milliseconds>(start_time - collision_time_).count();
        auto p_diff_ms = std::chrono::duration_cast<std::chrono::milliseconds>(start_time - plan_time_).count();

        // 충돌 해결을 위한 검사 로직 추가
        // 1. 충돌 시점부터 collision_timeout_max_ms_(default 8)초 미만
        // 2. 글로벌 패스가 plan_timeout_min_ms_(default 4)초 초과
        if (c_time_diff_ms < collision_timeout_max_ms_ && p_diff_ms > plan_timeout_min_ms_)
        {
            RCLCPP_INFO(logger_, "collision_time diff: %ldms, plan_time diff: %ldms", c_time_diff_ms, p_diff_ms);
            RCLCPP_INFO(logger_, "Unable to create path due to collision. Set current location to destination.");
            auto src = planner_->getSrc();
            planner_->setDst(src);
            planner_->generatePath(path);
            global_path = linearInterpolation(path, planner_->costmap_->getResolution());
            is_collision = true;
        }
        else
        {
            if (std::chrono::duration_cast<std::chrono::milliseconds>(start_time - plan_error_log_time2_).count() >
                1000)
            {
                plan_error_log_time2_ = start_time;
                RCLCPP_ERROR(logger_, "Could not generate path between the given poses");
            }
            global_path.poses.clear();
        }
    }
    global_path.header.stamp = clock_->now();
    global_path.header.frame_id = global_frame_;
    return is_collision;
}

nav_msgs::msg::Path PathPlanner::linearInterpolation(const std::vector<coordsW>& raw_path, const double& dist_bw_points)
{
    nav_msgs::msg::Path pa;

    geometry_msgs::msg::PoseStamped p1;
    for (unsigned int j = 0; j < raw_path.size() - 1; j++)
    {
        coordsW pt1 = raw_path[j];
        p1.pose.position.x = pt1.x;
        p1.pose.position.y = pt1.y;
        pa.poses.push_back(p1);

        coordsW pt2 = raw_path[j + 1];
        double distance = std::hypot(pt2.x - pt1.x, pt2.y - pt1.y);
        int loops = static_cast<int>(distance / dist_bw_points);
        double sin_alpha = (pt2.y - pt1.y) / distance;
        double cos_alpha = (pt2.x - pt1.x) / distance;
        for (int k = 1; k < loops; k++)
        {
            p1.pose.position.x = pt1.x + k * dist_bw_points * cos_alpha;
            p1.pose.position.y = pt1.y + k * dist_bw_points * sin_alpha;
            pa.poses.push_back(p1);
        }
    }

    return pa;
}

rcl_interfaces::msg::SetParametersResult PathPlanner::dynamicParametersCallback(
    std::vector<rclcpp::Parameter> parameters)
{
    rcl_interfaces::msg::SetParametersResult result;
    for (auto parameter : parameters)
    {
        const auto& type = parameter.get_type();
        const auto& name = parameter.get_name();

        if (type == ParameterType::PARAMETER_INTEGER)
        {
            if (name == name_ + ".how_many_corners")
            {
                planner_->how_many_corners_ = parameter.as_int();
            }
        }
        else if (type == ParameterType::PARAMETER_DOUBLE)
        {
            if (name == name_ + ".w_euc_cost")
            {
                planner_->w_euc_cost_ = parameter.as_double();
            }
            else if (name == name_ + ".w_traversal_cost")
            {
                planner_->w_traversal_cost_ = parameter.as_double();
            }
        }
        else if (type == ParameterType::PARAMETER_BOOL)
        {
            if (name == name_ + ".use_final_approach_orientation")
            {
                use_final_approach_orientation_ = parameter.as_bool();
            }
            else if (name == name_ + ".allow_unknown")
            {
                planner_->allow_unknown_ = parameter.as_bool();
            }
        }
    }

    result.successful = true;
    return result;
}

}  // namespace everybot_path_planner

#include "pluginlib/class_list_macros.hpp"
PLUGINLIB_EXPORT_CLASS(everybot_path_planner::PathPlanner, nav2_core::GlobalPlanner)
