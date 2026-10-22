#pragma once

#include <rclcpp/rclcpp.hpp>
#include <behaviortree_cpp_v3/condition_node.h>
#include <nav_msgs/msg/path.hpp>

namespace everybot_behavior_plugins {
    class PathDeviationCounterCondition : public BT::ConditionNode {
    public:
        PathDeviationCounterCondition(
            const std::string &condition_name,
            const BT::NodeConfiguration &conf);

        PathDeviationCounterCondition() = delete;

        ~PathDeviationCounterCondition() override = default;

        BT::NodeStatus tick() override;

        static BT::PortsList providedPorts() {
            return {
              BT::InputPort<nav_msgs::msg::Path>("path"),
                BT::InputPort<int>("max_change_count"),
                BT::InputPort<double>("length_ratio_threshold"),
            };
        }

    private:
        rclcpp::Node::SharedPtr node_;
        int change_count_;
        nav_msgs::msg::Path prev_path_;

        double computePathLength(const nav_msgs::msg::Path &path);
    };
} // everybot_behavior_plugins
