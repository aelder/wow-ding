FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils ca-certificates libpython3.11 python3-venv python3-tk python3-pil \
    libsecret-tools gnome-keyring dbus-x11 xauth xvfb xdotool desktop-file-utils \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt dev.txt linux/build-requirements.txt /tmp/deps/
RUN python3 -m venv /opt/build && /opt/build/bin/pip install --no-cache-dir \
    -r /tmp/deps/dev.txt -r /tmp/deps/build-requirements.txt
ENV PATH="/opt/build/bin:${PATH}"
WORKDIR /src
