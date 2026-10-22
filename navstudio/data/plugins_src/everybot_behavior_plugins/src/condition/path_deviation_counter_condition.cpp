#include "everybot_behavior_plugins/condition/path_deviation_counter_condition.hpp"

namespace everybot_behavior_plugins {
    PathDeviationCounterCondition::PathDeviationCounterCondition(
        const std::string &condition_name,
        const BT::NodeConfiguration &conf)
        : BT::ConditionNode(condition_name, conf),
          change_count_(0) {
        // BT 노드 내에서 사용할 rclcpp::Node 생성
        node_ = rclcpp::Node::make_shared("path_deviation_counter_condition");
    }

    BT::NodeStatus PathDeviationCounterCondition::tick() {
        // InputPort에서 데이터 가져오기
        nav_msgs::msg::Path current_path;
        int max_change_count;
        double length_ratio_threshold;

        if (!getInput("path", current_path)) {
            RCLCPP_WARN(node_->get_logger(), "Missing required input [path]");
            return BT::NodeStatus::FAILURE;
        }

        if (!getInput("max_change_count", max_change_count)) {
            RCLCPP_WARN(node_->get_logger(), "Missing required input [max_change_count]");
            return BT::NodeStatus::FAILURE;
        }

        if (!getInput("length_ratio_threshold", length_ratio_threshold)) {
            RCLCPP_WARN(node_->get_logger(), "Missing required input [length_ratio_threshold]");
            return BT::NodeStatus::FAILURE;
        }

        double current_length = computePathLength(current_path);
        double previous_length = computePathLength(prev_path_);

        if (prev_path_.poses.empty()) {
            prev_path_ = current_path;
            return BT::NodeStatus::SUCCESS;
        }

        if (previous_length > 0.01) {
            double length_ratio = current_length / previous_length;

            if (length_ratio > length_ratio_threshold) {
                change_count_++;
                RCLCPP_INFO(node_->get_logger(), "Path deviation detected! Count: (%d/%d)", change_count_, max_change_count);
            }
        }

        prev_path_ = current_path;

        if (change_count_ >= max_change_count) {
            RCLCPP_WARN(node_->get_logger(), "Path changed excessively. Returning FAILURE.");
            return BT::NodeStatus::FAILURE;
        }

        return BT::NodeStatus::SUCCESS;
    }

    double PathDeviationCounterCondition::computePathLength(const nav_msgs::msg::Path &path) {
        double length = 0.0;
        for (size_t i = 1; i < path.poses.size(); ++i) {
            const auto &p1 = path.poses[i - 1].pose.position;
            const auto &p2 = path.poses[i].pose.position;
            double dx = p2.x - p1.x;
            double dy = p2.y - p1.y;
            length += std::hypot(dx, dy);
        }
        return length;
    }
} // everybot_behavior_plugins

#include "behaviortree_cpp_v3/bt_factory.h"
BT_REGISTER_NODES(factory) {
    BT::NodeBuilder builder = [](const std::string &name, const BT::NodeConfiguration &config) {
        return std::make_unique<everybot_behavior_plugins::PathDeviationCounterCondition>(name, config);
    };

    factory.registerBuilder<everybot_behavior_plugins::PathDeviationCounterCondition>(
        "PathDeviationCounter", builder);
}
