# shellcheck shell=bash
# Interactive configuration wizard. Every answer can be pre-seeded through an
# answers file (install.sh --answers FILE) for unattended installs.

wizard() {
  local cores mem detected_ip
  cores=$(cpu_cores); mem=$(mem_total_gb); detected_ip=$(detect_primary_ip)

  step "Network / شبکه"
  cat <<EOF
  Users open Simorgh Meet in the browser at https://<address>. Use a DNS name if your
  organization has an internal DNS; otherwise use the server's IP address.
  کاربران از طریق مرورگر به آدرس https://<آدرس> وصل می‌شوند. اگر DNS داخلی دارید نام دامنه، وگرنه IP سرور را وارد کنید.
EOF
  ask PUBLIC_HOST "Server address (domain or IP) / آدرس سرور (دامنه یا IP)" "${PUBLIC_HOST:-$detected_ip}" is_hostname
  ask LAN_IP "Server LAN IP for media (WebRTC) / IP شبکه داخلی سرور برای صوت و تصویر" "${LAN_IP:-$detected_ip}" is_ipv4
  ask HTTPS_PORT "HTTPS port / پورت HTTPS" "${HTTPS_PORT:-443}" is_port
  ask HTTP_PORT "HTTP port (redirects to HTTPS) / پورت HTTP" "${HTTP_PORT:-80}" is_port
  ask JVB_PORT "Media UDP port / پورت UDP رسانه" "${JVB_PORT:-10000}" is_port

  ask_yn EXTERNAL_GUESTS "Will guests join from outside the LAN (internet/VPN-less)? / مهمانان خارجی از بیرون شبکه وصل می‌شوند؟" "${EXTERNAL_GUESTS:-n}"
  PUBLIC_IP=${PUBLIC_IP:-}
  ENABLE_TURN=${ENABLE_TURN:-0}
  if [ "$EXTERNAL_GUESTS" = 1 ]; then
    cat <<EOF
  For outside guests forward TCP ${HTTPS_PORT} and UDP ${JVB_PORT} from the firewall to ${LAN_IP}.
  برای مهمانان بیرونی، پورت TCP ${HTTPS_PORT} و UDP ${JVB_PORT} را در فایروال به ${LAN_IP} هدایت کنید.
EOF
    ask PUBLIC_IP "Public/NAT IP seen by outside guests / IP عمومی" "${PUBLIC_IP}" is_ipv4_or_empty
    ask_yn ENABLE_TURN "Enable built-in TURN relay (UDP/TCP 3478) for restrictive networks? / فعال‌سازی TURN" "${ENABLE_TURN:-n}"
  fi

  step "Security certificate / گواهی امنیتی (HTTPS)"
  cat <<EOF
  WebRTC (camera/microphone) requires HTTPS.
    self-signed : installer creates a local CA; distribute ca.crt to client computers (GPO/MDM) to avoid warnings.
    custom      : use your organization's certificate and private key (PEM files).
EOF
  ask_choice TLS_MODE "Certificate mode / نوع گواهی" "${TLS_MODE:-self-signed}" self-signed custom
  if [ "$TLS_MODE" = custom ]; then
    ask TLS_CERT_FILE "Path to certificate (PEM, full chain) / مسیر فایل گواهی" "${TLS_CERT_FILE:-}" is_file
    ask TLS_KEY_FILE "Path to private key (PEM) / مسیر کلید خصوصی" "${TLS_KEY_FILE:-}" is_file
  fi

  step "Organization & administrator / سازمان و مدیر سامانه"
  ask ORGANIZATION_NAME "Organization name / نام سازمان" "${ORGANIZATION_NAME:-سازمان}" is_nonempty
  ask TZ "Time zone / منطقه زمانی" "${TZ:-Asia/Tehran}" is_timezone
  ask ADMIN_USERNAME "Administrator username (latin) / نام کاربری مدیر" "${ADMIN_USERNAME:-admin}" is_username
  ask ADMIN_EMAIL "Administrator email / ایمیل مدیر" "${ADMIN_EMAIL:-admin@${PUBLIC_HOST}}" is_email
  ask ADMIN_DISPLAY_NAME "Administrator display name / نام نمایشی مدیر" "${ADMIN_DISPLAY_NAME:-مدیر سامانه}" is_nonempty
  if [ -z "${ADMIN_PASSWORD:-}" ]; then
    ask_secret ADMIN_PASSWORD "Administrator password / رمز عبور مدیر"
  fi

  step "Meeting access / دسترسی به جلسات"
  cat <<EOF
    internal : hosts log in with accounts created by 'simorgh-meet user add';
               guests (internal or external) join with the meeting link once a host has
               opened the room; hosts can turn on the lobby to admit guests one by one.
               Works today without the Simorgh web portal.
    jwt      : meetings are opened only with short-lived tokens issued by the Simorgh API
               (private/public meetings, invitations, roles). Requires the portal release.
EOF
  ask_choice MEET_AUTH_MODE "Meeting authentication / احراز هویت جلسات" "${MEET_AUTH_MODE:-internal}" internal jwt

  step "Features / امکانات"
  ask_yn ENABLE_RECORDING "Enable meeting recording & archive (Jibri, ~2-4 CPU cores per active recording)? / ضبط جلسات" "${ENABLE_RECORDING:-y}"
  if [ "$ENABLE_RECORDING" = 1 ]; then
    ask RECORDING_RETENTION_DAYS "Recording retention in days (0 = keep forever) / مدت نگهداری ضبط‌ها (روز)" "${RECORDING_RETENTION_DAYS:-365}" is_uint
  fi
  ask_yn ENABLE_AI "Enable Persian live transcription + automatic AI minutes? / رونویسی فارسی و صورت‌جلسه خودکار" "${ENABLE_AI:-y}"
  if [ "$ENABLE_AI" = 1 ] && { [ "$cores" -lt 8 ] || [ "$mem" -lt 16 ]; }; then
    warn "AI needs at least 8 CPU cores and 16 GB RAM (recommended 16 cores / 32 GB). Detected: ${cores} cores, ${mem} GB."
    ask_yn ENABLE_AI "Keep AI enabled anyway? / با این وجود فعال بماند؟" "n"
  fi
  ask_yn ENABLE_IDP "Install bundled identity server (Keycloak, Persian login, SSO/LDAP-ready)? / سرور هویت" "${ENABLE_IDP:-y}"

  step "Storage / محل ذخیره‌سازی"
  ask DATA_DIR "Data directory (database, recordings, minutes) / پوشه داده‌ها" "${DATA_DIR:-/var/lib/simorgh-meet}" is_abs_path
  local free; free=$(disk_free_gb "$DATA_DIR")
  [ "$free" -ge 50 ] || warn "Only ${free} GB free under ${DATA_DIR}. Recordings need ~0.5-1 GB per meeting hour."

  compute_sizing "$cores" "$mem"
  show_summary
  if [ "$NONINTERACTIVE" != 1 ]; then
    local go
    ask_yn go "Proceed with installation? / نصب ادامه یابد؟" "y"
    [ "$go" = 1 ] || die "Cancelled by user / لغو شد"
  fi
}

is_uint() { [[ $1 =~ ^[0-9]+$ ]]; }

compute_sizing() {
  local cores=$1 mem=$2
  # STT runs during meetings, the LLM mostly after them; give each a share and cap
  # container CPU so media (JVB) and recording always keep headroom.
  STT_WORKERS=${STT_WORKERS:-$(( cores >= 16 ? 3 : 2 ))}
  STT_CPU_THREADS=${STT_CPU_THREADS:-$(( cores >= 16 ? 4 : 2 ))}
  STT_CPU_LIMIT=${STT_CPU_LIMIT:-$(( cores / 2 > 2 ? cores / 2 : 2 ))}
  LLM_THREADS=${LLM_THREADS:-$(( cores / 2 > 2 ? cores / 2 : 2 ))}
  LLM_CPU_LIMIT=${LLM_CPU_LIMIT:-$(( cores * 3 / 4 > 2 ? cores * 3 / 4 : 2 ))}
  LLM_CONTEXT=${LLM_CONTEXT:-$(( mem >= 32 ? 16384 : 8192 ))}
  LLM_CHUNK_CHARS=${LLM_CHUNK_CHARS:-$(( mem >= 32 ? 12000 : 6000 ))}
}

show_summary() {
  local url="https://${PUBLIC_HOST}"; [ "$HTTPS_PORT" = 443 ] || url="${url}:${HTTPS_PORT}"
  step "Summary / خلاصه"
  cat <<EOF
  URL                 : ${url}
  Media               : ${LAN_IP} UDP ${JVB_PORT}${PUBLIC_IP:+ (public ${PUBLIC_IP})}
  TLS                 : ${TLS_MODE}
  Organization        : ${ORGANIZATION_NAME}  (TZ ${TZ})
  Admin               : ${ADMIN_USERNAME} <${ADMIN_EMAIL}>
  Meeting auth        : ${MEET_AUTH_MODE}
  Recording           : $( [ "$ENABLE_RECORDING" = 1 ] && echo "on (retention ${RECORDING_RETENTION_DAYS:-365} days)" || echo off)
  AI minutes          : $( [ "$ENABLE_AI" = 1 ] && echo "on (STT ${STT_WORKERS}x${STT_CPU_THREADS} threads, LLM ${LLM_THREADS} threads, ctx ${LLM_CONTEXT})" || echo off)
  Identity server     : $( [ "$ENABLE_IDP" = 1 ] && echo on || echo off)
  TURN relay          : $( [ "$ENABLE_TURN" = 1 ] && echo on || echo off)
  Install dir         : ${SIMORGH_HOME}
  Data dir            : ${DATA_DIR}
EOF
}
