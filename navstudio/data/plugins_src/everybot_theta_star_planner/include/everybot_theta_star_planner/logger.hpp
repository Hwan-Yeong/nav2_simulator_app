#pragma once

#include <rclcpp/rclcpp.hpp>

#define RCL_LOG_INFO(logger, format, ...)  RCLCPP_INFO(logger, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)
#define RCL_LOG_WARN(logger, format, ...)  RCLCPP_WARN(logger, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)
#define RCL_LOG_DEBUG(logger, format, ...) RCLCPP_DEBUG(logger, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)
#define RCL_LOG_ERROR(logger, format, ...) RCLCPP_ERROR(logger, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)
#define RCL_LOG_FATAL(logger, format, ...) RCLCPP_FATAL(logger, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)

#define RCL_LOG_INFO_ONCE(logger, format, ...)  RCLCPP_INFO_ONCE(logger, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)
#define RCL_LOG_WARN_ONCE(logger, format, ...)  RCLCPP_WARN_ONCE(logger, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)
#define RCL_LOG_DEBUG_ONCE(logger, format, ...) RCLCPP_DEBUG_ONCE(logger, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)
#define RCL_LOG_ERROR_ONCE(logger, format, ...) RCLCPP_ERROR_ONCE(logger, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)
#define RCL_LOG_FATAL_ONCE(logger, format, ...) RCLCPP_FATAL_ONCE(logger, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)

#define RCL_LOG_INFO_THROTTLE(logger, clock, duration, format, ...) RCLCPP_INFO_THROTTLE(logger, clock, duration, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)
#define RCL_LOG_WARN_THROTTLE(logger, clock, duration, format, ...) RCLCPP_WARN_THROTTLE(logger, clock, duration, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)
#define RCL_LOG_DEBUG_THROTTLE(logger, clock, duration, format, ...) RCLCPP_DEBUG_THROTTLE(logger, clock, duration, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)
#define RCL_LOG_ERROR_THROTTLE(logger, clock, duration, format, ...) RCLCPP_ERROR_THROTTLE(logger, clock, duration, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)
#define RCL_LOG_FATAL_THROTTLE(logger, clock, duration, format, ...) RCLCPP_FATAL_THROTTLE(logger, clock, duration, "%s():%d:" format, __func__, __LINE__, ##__VA_ARGS__)