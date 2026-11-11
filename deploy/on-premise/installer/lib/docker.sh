# shellcheck shell=bash
# Offline installation of Docker Engine (static binaries) + Compose plugin.

DOCKER_MIN_MAJOR=24

docker_installed_ok() {
  have docker || return 1
  local v
  v=$(docker version --format '{{.Server.Version}}' 2>/dev/null) || return 1
  [ "${v%%.*}" -ge "$DOCKER_MIN_MAJOR" ] 2>/dev/null
}

compose_installed_ok() { docker compose version >/dev/null 2>&1; }

install_docker_static() {
  local bundle=$1 tgz='' f
  for f in "$bundle"/vendor/docker/docker-[0-9]*.tgz; do [ -f "$f" ] && tgz=$f && break; done
  [ -n "$tgz" ] || die "Docker static archive missing in bundle (vendor/docker)."
  info "Installing Docker Engine from $(basename "$tgz")"

  local tmp; tmp=$(mktemp -d)
  tar -xzf "$tgz" -C "$tmp"
  install -m 0755 "$tmp"/docker/* /usr/bin/
  rm -rf "$tmp"

  getent group docker >/dev/null || groupadd --system docker
  install -d -m 0755 /etc/docker
  if [ ! -f /etc/docker/daemon.json ]; then
    cat >/etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5" },
  "live-restore": true,
  "userland-proxy": false,
  "default-address-pools": [ { "base": "172.30.0.0/16", "size": 24 } ]
}
JSON
  fi

  install -m 0644 "$bundle/systemd/containerd.service" /etc/systemd/system/containerd.service
  install -m 0644 "$bundle/systemd/docker.service" /etc/systemd/system/docker.service
  install -m 0644 "$bundle/systemd/docker.socket" /etc/systemd/system/docker.socket
  systemctl daemon-reload
  systemctl enable --now containerd.service
  systemctl enable --now docker.socket docker.service
  for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
  docker info >/dev/null 2>&1 || die "Docker daemon did not start; see: journalctl -u docker"
  ok "Docker $(docker version --format '{{.Server.Version}}') running"
}

install_compose_plugin() {
  local bundle=$1
  local bin="$bundle/vendor/docker/docker-compose-linux-x86_64"
  [ -f "$bin" ] || die "Compose plugin missing in bundle (vendor/docker)."
  install -d -m 0755 /usr/local/lib/docker/cli-plugins
  install -m 0755 "$bin" /usr/local/lib/docker/cli-plugins/docker-compose
  ok "$(docker compose version)"
}

ensure_docker() {
  local bundle=$1
  if docker_installed_ok; then
    ok "Existing Docker $(docker version --format '{{.Server.Version}}') detected; keeping it"
  else
    if have docker || have dockerd; then
      warn "Existing Docker is older than ${DOCKER_MIN_MAJOR}.x or not running; installing bundled version"
      systemctl stop docker.service docker.socket containerd.service 2>/dev/null || true
    fi
    have iptables || die "'iptables' is required by Docker networking but missing. Install your distro's iptables package (it is on the OS install media)."
    install_docker_static "$bundle"
  fi
  # Always ship the tested Compose version alongside.
  install_compose_plugin "$bundle"
}

load_images() {
  local bundle=$1 f
  local files=("$bundle"/images/*.tar.gz)
  [ -e "${files[0]}" ] || die "No images found in bundle (images/*.tar.gz)."
  local total=${#files[@]} n=0
  for f in "${files[@]}"; do
    n=$((n + 1))
    info "Loading image $n/$total: $(basename "$f")"
    docker load -i "$f" >>"$LOG_FILE" 2>&1 || die "docker load failed for $f"
  done
  ok "All $total images loaded"
}
