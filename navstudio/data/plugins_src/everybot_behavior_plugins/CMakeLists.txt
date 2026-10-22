cmake_minimum_required(VERSION 3.8)
project(everybot_behavior_plugins)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(nav2_util REQUIRED)
find_package(nav2_core REQUIRED)
find_package(nav2_behavior_tree REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(behaviortree_cpp_v3 REQUIRED)

set(dependencies
        rclcpp
        nav2_util
        nav2_core
        nav2_behavior_tree
        tf2_ros
        tf2_geometry_msgs
        geometry_msgs
        behaviortree_cpp_v3
)

include_directories(include)

add_library(everybot_are_poses_near_condition_bt_node SHARED src/condition/are_poses_near_condition.cpp)
list(APPEND plugin_libs everybot_are_poses_near_condition_bt_node)

add_library(everybot_goal_updater_node_bt_node SHARED src/decorator/goal_updater_node.cpp)
list(APPEND plugin_libs everybot_goal_updater_node_bt_node)

foreach(bt_plugin ${plugin_libs})
  ament_target_dependencies(${bt_plugin} ${dependencies})
  target_compile_definitions(${bt_plugin} PRIVATE BT_PLUGIN_EXPORT)
endforeach()

install(TARGETS ${plugin_libs}
        ARCHIVE DESTINATION lib
        LIBRARY DESTINATION lib
        RUNTIME DESTINATION bin
)


install(DIRECTORY include/
        DESTINATION include/
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_export_include_directories(include)
ament_export_libraries(${plugin_libs})
ament_export_dependencies(${dependencies})
ament_package()
