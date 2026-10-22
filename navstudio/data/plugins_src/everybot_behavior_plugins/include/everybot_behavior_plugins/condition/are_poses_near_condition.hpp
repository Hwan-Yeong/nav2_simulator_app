#pragma once

#include "rclcpp/rclcpp.hpp"
#include "tf2_ros/buffer.h"
#include "tf2_geometry_msgs/tf2_geometry_msgs.hpp"
#include "geometry_msgs/msg/pose_stamped.hpp"
#include "behaviortree_cpp_v3/condition_node.h"

namespace everybot_behavior_plugins {
    /**
     * @brief A BT::ConditionNode that returns SUCCESS when a specified goal
     * is reached and FAILURE otherwise
     */
    class ArePosesNearCondition : public BT::ConditionNode {
    public:
        /**
         * @brief A constructor for nav2_behavior_tree::ArePosesNearCondition
         * @param condition_name Name for the XML tag for this node
         * @param conf BT node configuration
         */
        ArePosesNearCondition(
            const std::string &condition_name,
            const BT::NodeConfiguration &conf);

        /**
         ** @brief A destructor for nav2_behavior_tree::ArePosesNearCondition
         *
         */
        ~ArePosesNearCondition() override = default;

        /**
         * @brief The main override required by a BT action
         * @return BT::NodeStatus Status of tick execution
         */
        BT::NodeStatus tick() override;

        /**
         * @brief Function to read parameters and initialize class variables
         */
        void initialize();

        /**
         * @brief Checks if the current robot pose lies within a given distance from the goal
         * @return bool true when goal is reached, false otherwise
         */
        bool arePosesNearby();

        /**
         * @brief Creates list of BT ports
         * @return BT::PortsList Containing node-specific ports
         */
        static BT::PortsList providedPorts() {
            return {
                BT::InputPort<geometry_msgs::msg::PoseStamped>("ref_pose", "Destination"),
                BT::InputPort<geometry_msgs::msg::PoseStamped>("target_pose", "Destination"),
                BT::InputPort<std::string>("global_frame", "Global frame"),
                BT::InputPort<double>("tolerance", 0.5, "Tolerance")
            };
        }

    private:
        bool transformPoseInTargetFrame(
            const geometry_msgs::msg::PoseStamped &input_pose,
            geometry_msgs::msg::PoseStamped &transformed_pose,
            tf2_ros::Buffer &tf_buffer, const std::string target_frame,
            const double transform_timeout);

        rclcpp::Node::SharedPtr node_;
        std::shared_ptr<tf2_ros::Buffer> tf_;
        double transform_tolerance_;
        std::string global_frame_;

        bool initialized_;
    };
} // everybot_behavior_plugins
