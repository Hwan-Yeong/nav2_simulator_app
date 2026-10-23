"""sim2d + the Nav2 server set (same topology as the production navigation_launch.py).

ros2 launch nav_sim.launch.py params_file:=P map:=M robot_file:=R [sim_params:=S] [start_pose:="[x,y,th]"] [log_level:=warn]
                              [perception:=true]   (range-sensor perception node, robot perception mode 'rules')
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

LIFECYCLE = ['map_server', 'controller_server', 'smoother_server', 'planner_server', 'behavior_server',
             'bt_navigator', 'velocity_smoother']


def generate_launch_description():
    params = LaunchConfiguration('params_file')
    map_yaml = LaunchConfiguration('map')
    log_level = LaunchConfiguration('log_level')
    remaps = [('/tf', 'tf'), ('/tf_static', 'tf_static')]
    common = dict(output='screen', arguments=['--ros-args', '--log-level', log_level])
    sim = ExecuteProcess(
        cmd=[LaunchConfiguration('python'), '-m', 'navstudio.sim.sim2d', '--ros-args',
             '-p', ['map_yaml:=', map_yaml], '-p', ['robot_file:=', LaunchConfiguration('robot_file')],
             '-p', ['start_pose:=', LaunchConfiguration('start_pose')],
             '--params-file', LaunchConfiguration('sim_params'), '--log-level', log_level],
        output='screen')
    perception = ExecuteProcess(
        cmd=[LaunchConfiguration('python'), '-m', 'navstudio.sim.perception', '--ros-args',
             '-p', ['robot_file:=', LaunchConfiguration('robot_file')], '--params-file', params, '--log-level', log_level],
        output='screen', condition=IfCondition(LaunchConfiguration('perception')))
    nodes = [
        sim,
        perception,
        Node(package='nav2_map_server', executable='map_server', name='map_server',
             parameters=[params, {'yaml_filename': map_yaml}], remappings=remaps, **common),
        Node(package='nav2_controller', executable='controller_server', name='controller_server',
             parameters=[params], remappings=remaps + [('cmd_vel', 'cmd_vel_nav')], **common),
        Node(package='nav2_smoother', executable='smoother_server', name='smoother_server',
             parameters=[params], remappings=remaps, **common),
        Node(package='nav2_planner', executable='planner_server', name='planner_server',
             parameters=[params], remappings=remaps, **common),
        Node(package='nav2_behaviors', executable='behavior_server', name='behavior_server',
             parameters=[params], remappings=remaps, **common),
        Node(package='nav2_bt_navigator', executable='bt_navigator', name='bt_navigator',
             parameters=[params], remappings=remaps, **common),
        Node(package='nav2_velocity_smoother', executable='velocity_smoother', name='velocity_smoother',
             parameters=[params], remappings=remaps + [('cmd_vel', 'cmd_vel_nav'),
                                                       ('cmd_vel_smoothed', 'cmd_vel_smoothed')], **common),
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager', name='lifecycle_manager_navigation',
             parameters=[{'use_sim_time': True, 'autostart': True, 'bond_timeout': 0.0, 'node_names': LIFECYCLE}],
             **common),
    ]
    return LaunchDescription([
        DeclareLaunchArgument('params_file'),
        DeclareLaunchArgument('map'),
        DeclareLaunchArgument('robot_file'),
        DeclareLaunchArgument('sim_params'),
        DeclareLaunchArgument('start_pose', default_value='[0.0, 0.0, 0.0]'),
        DeclareLaunchArgument('log_level', default_value='warn'),
        DeclareLaunchArgument('python', default_value='python3'),
        DeclareLaunchArgument('perception', default_value='false'),
    ] + nodes)
