# shellcheck shell=bash
# Common helpers for the Simorgh Meet installer and management CLI.

if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_RED=$'\033[31m'; C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'; C_CYAN=$'\033[36m'
else
  C_RESET=''; C_BOLD=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_CYAN=''
fi

LOG_FILE=${LOG_FILE:-/var/log/simorgh-meet-install.log}

_log_to_file() { printf '%s %s\n' "$(date '+%F %T')" "$*" >>"$LOG_FILE" 2>/dev/null || true; }
info()  { printf '%s[i]%s %s\n' "$C_CYAN" "$C_RESET" "$*"; _log_to_file "INFO $*"; }
ok()    { printf '%s[✓]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; _log_to_file "OK   $*"; }
warn()  { printf '%s[!]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; _log_to_file "WARN $*"; }
die()   { printf '%s[x]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; _log_to_file "FAIL $*"; exit 1; }
step()  { printf '\n%s==> %s%s\n' "$C_BOLD" "$*" "$C_RESET"; _log_to_file "STEP $*"; }

require_root() { [ "$(id -u)" -eq 0 ] || die "Run as root (sudo) / با دسترسی root اجرا کنید."; }

have() { command -v "$1" >/dev/null 2>&1; }

# random_secret [length] -> alphanumeric secret from the kernel CSPRNG
random_secret() {
  local len=${1:-32} out=''
  while [ "${#out}" -lt "$len" ]; do
    out+=$(head -c 96 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')
  done
  printf '%s' "${out:0:$len}"
}

# ---------------------------------------------------------------- prompting
NONINTERACTIVE=${NONINTERACTIVE:-0}

# ask VAR "Question (fa / en)" default [validator]
ask() {
  local var=$1 question=$2 default=${3:-} validator=${4:-} answer
  # Pre-seeded from an answers file / environment wins in non-interactive mode.
  if [ -n "${!var:-}" ] && [ "$NONINTERACTIVE" = 1 ]; then
    answer=${!var}
  elif [ "$NONINTERACTIVE" = 1 ]; then
    answer=$default
  else
    local current=${!var:-$default}
    while true; do
      read -r -p "${C_BOLD}?${C_RESET} ${question} [${current}]: " answer </dev/tty || true
      answer=${answer:-$current}
      if [ -z "$validator" ] || "$validator" "$answer"; then break; fi
      warn "Invalid value / مقدار نامعتبر: '$answer'"
    done
  fi
  if [ -n "$validator" ] && ! "$validator" "$answer"; then
    die "Invalid value for $var: '$answer'"
  fi
  printf -v "$var" '%s' "$answer"
}

# ask_secret VAR "Question" -> hidden input with confirmation; empty = generate
ask_secret() {
  local var=$1 question=$2 a b
  if [ "$NONINTERACTIVE" = 1 ]; then
    [ -n "${!var:-}" ] || printf -v "$var" '%s' "$(random_secret 16)"
    return
  fi
  while true; do
    read -r -s -p "${C_BOLD}?${C_RESET} ${question} (empty = generate / خالی = تولید خودکار): " a </dev/tty || true; echo
    if [ -z "$a" ]; then printf -v "$var" '%s' "$(random_secret 16)"; return; fi
    if [ "${#a}" -lt 10 ]; then warn "At least 10 characters / حداقل ۱۰ کاراکتر"; continue; fi
    read -r -s -p "  Repeat / تکرار: " b </dev/tty || true; echo
    [ "$a" = "$b" ] && { printf -v "$var" '%s' "$a"; return; }
    warn "Passwords do not match / رمزها یکسان نیستند"
  done
}

# ask_yn VAR "Question" default(y|n)
ask_yn() {
  local var=$1 question=$2 default=${3:-y}
  ask "$var" "$question (y/n)" "${!var:-$default}" is_yn
  case ${!var} in [Yy]*|1|true) printf -v "$var" '1' ;; *) printf -v "$var" '0' ;; esac
}

# ask_choice VAR "Question" default option1 option2 ...
ask_choice() {
  local var=$1 question=$2 default=$3; shift 3
  local options="$*"
  _in_options() { local o; for o in $options; do [ "$o" = "$1" ] && return 0; done; return 1; }
  ask "$var" "$question {${options// /|}}" "$default" _in_options
}

# ---------------------------------------------------------------- validators
is_yn()      { case $1 in [YyNn]|[Yy]es|[Nn]o|0|1|true|false) return 0 ;; *) return 1 ;; esac; }
is_port()    { [[ $1 =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
is_ipv4()    {
  [[ $1 =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
  local o; for o in "${BASH_REMATCH[@]:1}"; do [ "$o" -le 255 ] || return 1; done
}
is_ipv4_or_empty() { [ -z "$1" ] || is_ipv4 "$1"; }
is_hostname() { is_ipv4 "$1" || [[ $1 =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$ ]]; }
is_abs_path() { [[ $1 == /* ]] && [[ $1 != *' '* ]]; }
is_email()   { [[ $1 =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; }
is_username(){ [[ $1 =~ ^[a-z][a-z0-9._-]{2,31}$ ]]; }
is_nonempty(){ [ -n "$1" ]; }
is_timezone(){ [ -e "/usr/share/zoneinfo/$1" ] || [ "$1" = "Asia/Tehran" ] || [ "$1" = "UTC" ]; }
is_file()    { [ -f "$1" ]; }

# ---------------------------------------------------------------- system facts
detect_primary_ip() {
  local ip=''
  if have ip; then
    ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')
    [ -n "$ip" ] || ip=$(ip -4 -o addr show scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]; exit}')
  fi
  [ -n "$ip" ] || ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  printf '%s' "${ip:-127.0.0.1}"
}

cpu_cores()   { nproc 2>/dev/null || getconf _NPROCESSORS_ONLN; }
mem_total_gb(){ awk '/MemTotal/ {printf "%d", $2/1024/1024 + 0.5}' /proc/meminfo; }
disk_free_gb(){ local p=$1; while [ ! -d "$p" ]; do p=$(dirname "$p"); done; df -Pk "$p" | awk 'NR==2 {printf "%d", $4/1024/1024}'; }
cpu_has()     { grep -qw "$1" /proc/cpuinfo; }

port_in_use() { # port proto(tcp|udp)
  local port=$1 proto=${2:-tcp}
  if have ss; then
    ss -H -l -n "--$proto" 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${port}\$"
  else
    return 1
  fi
}
