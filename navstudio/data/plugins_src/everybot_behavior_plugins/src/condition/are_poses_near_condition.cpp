#include "everybot_behavior_plugins/condition/are_poses_near_condition.hpp"

#include <memory>
#include <string>

namespace everybot_behavior_plugins {
    ArePosesNearCondition::ArePosesNearCondition(
        const std::string &condition_name,
        const BT::NodeConfiguration &conf)
        : BT::ConditionNode(condition_name, conf) {
        auto node = config().blackboard->get<rclcpp::Node::SharedPtr>("node");
        getInput("global_frame", global_frame_);
    }

    void ArePosesNearCondition::initialize() {
        node_ = config().blackboard->get<rclcpp::Node::SharedPtr>("node");
        tf_ = config().blackboard->get<std::shared_ptr<tf2_ros::Buffer> >("tf_buffer");
        node_->get_parameter("transform_tolerance", transform_tolerance_);

        initialized_ = true;
    }

    BT::NodeStatus ArePosesNearCondition::tick() {
        if (!initialized_) {
            initialize();
        }

        if (arePosesNearby()) {
            return BT::NodeStatus::SUCCESS;
        }
        return BT::NodeStatus::FAILURE;
    }

    bool ArePosesNearCondition::arePosesNearby() {
        geometry_msgs::msg::PoseStamped pose1, pose2;
        double tol;
        getInput("ref_pose", pose1);
        getInput("target_pose", pose2);
        getInput("tolerance", tol);

        if (pose1.header.frame_id != pose2.header.frame_id) {
            if (transformPoseInTargetFrame(
                    pose1, pose1, *tf_, global_frame_, transform_tolerance_) ||
                transformPoseInTargetFrame(
                    pose2, pose2, *tf_, global_frame_, transform_tolerance_)) {
                RCLCPP_ERROR(node_->get_logger(), "Failed to transform poses to the same frame");
                return false;
            }
        }

        double dx = pose1.pose.position.x - pose2.pose.position.x;
        double dy = pose1.pose.position.y - pose2.pose.position.y;
        return (dx * dx + dy * dy) <= (tol * tol);
    }

    bool ArePosesNearCondition::transformPoseInTargetFrame(
        const geometry_msgs::msg::PoseStamped &input_pose,
        geometry_msgs::msg::PoseStamped &transformed_pose,
        tf2_ros::Buffer &tf_buffer, const std::string target_frame,
        const double transform_timeout) {
        static rclcpp::Logger logger = rclcpp::get_logger("transformPoseInTargetFrame");

        try {
            transformed_pose = tf_buffer.transform(
                input_pose, target_frame,
                tf2::durationFromSec(transform_timeout));
            return true;
        } catch (tf2::LookupException &ex) {
            RCLCPP_ERROR(
                logger,
                "No Transform available Error looking up target frame: %s\n", ex.what());
        } catch (tf2::ConnectivityException &ex) {
            RCLCPP_ERROR(
                logger,
                "Connectivity Error looking up target frame: %s\n", ex.what());
        } catch (tf2::ExtrapolationException &ex) {
            RCLCPP_ERROR(
                logger,
                "Extrapolation Error looking up target frame: %s\n", ex.what());
        } catch (tf2::TimeoutException &ex) {
            RCLCPP_ERROR(
                logger,
                "Transform timeout with tolerance: %.4f", transform_timeout);
        } catch (tf2::TransformException &ex) {
            RCLCPP_ERROR(
                logger, "Failed to transform from %s to %s",
                input_pose.header.frame_id.c_str(), target_frame.c_str());
        }

        return false;
    }
} // everybot_behavior_plugins

#include "behaviortree_cpp_v3/bt_factory.h"
BT_REGISTER_NODES(factory) {
    BT::NodeBuilder builder = [](const std::string &name, const BT::NodeConfiguration & config) {
        return std::make_unique<everybot_behavior_plugins::ArePosesNearCondition>(name, config);
    };

    factory.registerBuilder<everybot_behavior_plugins::ArePosesNearCondition>(
      "ArePosesNear", builder);
}