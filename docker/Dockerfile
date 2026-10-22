# Nav Studio — ROS 2 Humble + Nav2 + Nav Studio in one image.
#   docker compose -f docker/compose.yml up --build      → http://localhost:8765
FROM ros:humble-ros-base-jammy

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-humble-navigation2 \
      python3-pip python3-colcon-common-extensions build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/navstudio
COPY pyproject.toml README.md ./
COPY navstudio ./navstudio
# Ubuntu 22.04 ships pip 22.0 / setuptools 59, which cannot read PEP 621 metadata: upgrade first
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
 && python3 -m pip install --no-cache-dir ".[tune]" \
 && command -v navstudio

# Everybot planner / BT plugins are built into the image (user data lives in the /data volume)
RUN NAVSTUDIO_HOME=/opt/navstudio/build navstudio build-plugins
ENV NAVSTUDIO_OVERLAY=/opt/navstudio/build/overlay/install/setup.bash \
    NAVSTUDIO_HOME=/data

EXPOSE 8765
VOLUME ["/data"]
CMD ["navstudio", "run", "--host", "0.0.0.0", "--port", "8765", "--no-browser"]
