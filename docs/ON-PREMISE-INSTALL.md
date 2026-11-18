# Simorgh Meet — راهنمای بسته نصب آفلاین (On-Premise)

**نسخه بسته:** 0.2.0 · **موتور رسانه:** Jitsi `stable-11031` · **هدف:** یک سرور لینوکس x86_64 بدون GPU و بدون نیاز به اینترنت

> English summary: Simorgh Meet ships as **one self-extracting file** (`simorgh-meet-<ver>.run`)
> that contains the Docker Engine static binaries, the Compose plugin, every container image,
> and the Persian speech-recognition + minutes LLM models. It is built **once** on a machine
> with internet access and installed on servers that have **no internet**. An interactive
> wizard asks for IP/domain, ports, certificate, organization, administrator and features.

---

## ۱. معماری بسته

```
                      ┌──────────────────────── simorgh-meet-<ver>.run ───────────────────────┐
                      │ install.sh + wizard │ docker static + compose │ images/*.tar.gz │ models │
                      └───────────────────────────────────────────────────────────────────────┘
Browser (https) ──► web (Jitsi + nginx) ──┬── /            Jitsi Meet UI (فارسی)
                                          ├── /api/        simorgh-api (NestJS) ──► PostgreSQL
                                          ├── /auth/       Keycloak (OIDC, ورود فارسی، آماده LDAP/AD)
                                          └── /xmpp-websocket ► prosody ◄─ jicofo ─► jvb (UDP 10000) ◄─ media
                       prosody ◄── jibri (ضبط)            ──► /var/lib/simorgh-meet/jitsi/jibri/recordings
                       prosody ◄── transcriber (Jigasi) ──WS──► stt (Whisper فارسی، CPU) ──► stt/ (صوت هر سخنران)
                                         │ transcript.json                       │
                                         └──────────► ai-worker ◄────────────────┘
                                                        │  refine → LLM (llama.cpp, CPU) → صورت‌جلسه
                                                        └──► PostgreSQL (minutes, action_items) + minutes/*.md
```

| سرویس | ایمیج | پروفایل |
|---|---|---|
| web, prosody, jicofo, jvb | `jitsi/*:stable-11031` | همیشه |
| jibri (ضبط) | `jitsi/jibri:stable-11031` | `recording` |
| transcriber (Jigasi) | `jitsi/jigasi:stable-11031` | `ai` |
| stt, ai-worker | `simorgh-meet/ai:<ver>` (faster-whisper + sherpa-onnx) | `ai` |
| llm | `ghcr.io/ggml-org/llama.cpp:server-b12282` | `ai` |
| api | `simorgh-meet/api:<ver>` | همیشه |
| postgres | `postgres:16.15-bookworm` | همیشه |
| keycloak | `keycloak/keycloak:26.8.2` | `idp` |
| coturn | `coturn/coturn:4.18.0` | `turn` |

فایل‌های compose جیتسی **بدون تغییر** از مخزن رسمی (`deploy/on-premise/compose/jitsi`) آورده شده‌اند و
همه شخصی‌سازی‌ها در `compose/simorgh.yml` و `.env` تولیدشده توسط نصب‌کننده است؛ بنابراین ارتقای جیتسی
فقط جایگزینی فایل‌ها و تغییر نسخه است.

---

## ۲. سخت‌افزار پیشنهادی (برآورد اولیه — باید با تست بار تأیید شود)

| سناریو | CPU | RAM | دیسک |
|---|---|---|---|
| حداقل (بدون AI) | ۴ هسته | ۸ GB | ۱۰۰ GB SSD |
| حداقل با صورت‌جلسه AI (کندتر، context کوچک) | ۸ هسته با AVX2 | ۱۶ GB | ۲۵۰ GB SSD |
| **پیشنهادی** (۲ تا ۳ جلسه هم‌زمان، تا ~۳۰ نفر، ضبط + AI) | **۱۶ هسته با AVX2** | **۳۲ GB** | **۵۰۰ GB SSD** |

- هر ضبط فعال (Jibri) حدود ۲ تا ۴ هسته مصرف می‌کند؛ ضبط ویدیو ~۰٫۵ تا ۱ GB در ساعت.
- مدل گفتار (Whisper large-v3-turbo فارسی، int8) حدود ۱ تا ۱٫۵ GB و مدل زبانی (Qwen3.5-9B Q4_K_M) حدود ۶ تا ۷ GB رم مصرف می‌کند.
- پهنای باند رسانه (JVB) به تعداد شرکت‌کنندگان بستگی دارد؛ ظرفیت واقعی را پیش از تعهد با تست بار بسنجید.
- سیستم‌عامل: هر توزیع لینوکس x86_64 با systemd و کرنل ≥ 4.18 و `iptables` (Ubuntu 22.04/24.04، Debian 12، RHEL/Rocky/Alma 8/9).

---

## ۳. مرحله ۱ — ساخت بسته (فقط یک‌بار، روی سیستم دارای اینترنت)

پیش‌نیاز: Linux x86_64، Docker، `curl`، `python3`، حدود ۴۰ GB فضای خالی.

```bash
git clone https://github.com/shahram-tabasi/simorgh_meet && cd simorgh_meet
```

دانلود باینری‌ها و مدل‌ها (Docker Engine، Compose، مدل گفتار فارسی، مدل زبانی) با بررسی SHA-256 و ثبت در `artifacts.lock`:

```bash
tools/package/fetch-artifacts.sh
```

ساخت ایمیج‌های سیمرغ، دریافت ایمیج‌های ثالث و خروجی گرفتن از همه:

```bash
tools/package/build-images.sh
```

ساخت فایل نصب واحد (و در صورت نیاز تقسیم برای انتقال با فلش):

```bash
tools/package/build-bundle.sh --split 4G
```

خروجی در `tools/package/out/`: `simorgh-meet-0.2.0.run` و `simorgh-meet-0.2.0.run.sha256`.

- همه نسخه‌ها در `tools/package/versions.env` ثابت شده‌اند. برای استفاده از mirror هاگینگ‌فیس: `HF_ENDPOINT=https://… tools/package/fetch-artifacts.sh`.
- دانلودها cache می‌شوند؛ اجرای مجدد فقط فایل‌های تغییرکرده را می‌گیرد.
- برای مدل گفتار سفارشی (مثلاً مدل تنظیم‌شده کرمانی) بخش ۴ سند `AI-MINUTES-AND-PERSIAN-STT.md` را ببینید.

---

## ۴. مرحله ۲ — نصب روی سرور (بدون اینترنت)

```bash
sha256sum -c simorgh-meet-0.2.0.run.sha256
```

```bash
sudo sh simorgh-meet-0.2.0.run
```

اگر فایل تقسیم شده است، ابتدا قطعات را به هم بچسبانید:

```bash
cat simorgh-meet-0.2.0.run.part-* > simorgh-meet-0.2.0.run
```

نصب‌کننده به ترتیب: بررسی پیش‌نیازها → بررسی SHA-256 همه فایل‌ها → **ویزارد پیکربندی** → نصب Docker
(اگر Docker ≥ 24 موجود باشد همان حفظ می‌شود) → بارگذاری ایمیج‌ها → تولید رمزها، گواهی و تنظیمات →
راه‌اندازی و بررسی سلامت → ساخت حساب مدیر.

### سؤال‌های ویزارد

| موضوع | توضیح | پیش‌فرض |
|---|---|---|
| آدرس سرور | دامنه داخلی یا IP که کاربران در مرورگر وارد می‌کنند | IP اصلی سرور |
| IP شبکه داخلی | IP که صوت/تصویر (WebRTC) روی آن اعلام می‌شود | IP اصلی |
| پورت‌ها | HTTPS، HTTP (ریدایرکت)، UDP رسانه | 443 / 80 / 10000 |
| مهمان خارجی | اگر بله: IP عمومی (NAT) و فعال‌سازی TURN اختیاری | خیر |
| گواهی | `self-signed` (CA محلی ساخته می‌شود) یا `custom` (گواهی سازمان) | self-signed |
| سازمان و منطقه زمانی | نام سازمان (در صورت‌جلسه‌ها) | Asia/Tehran |
| مدیر سامانه | نام کاربری، ایمیل، نام نمایشی، رمز (خالی = تولید خودکار) | admin |
| احراز هویت جلسه | `internal` (میزبان با حساب، مهمان با لینک) یا `jwt` (توکن از API سیمرغ) | internal |
| ضبط | فعال/غیرفعال و مدت نگهداری (روز) | فعال / ۳۶۵ |
| صورت‌جلسه AI | رونویسی فارسی و صورت‌جلسه خودکار | فعال |
| سرور هویت | Keycloak (ورود فارسی، آماده اتصال LDAP/Active Directory) | فعال |
| محل داده‌ها | پایگاه داده، ضبط‌ها، رونوشت‌ها و صورت‌جلسه‌ها | `/var/lib/simorgh-meet` |

نصب بدون تعامل: `answers.example.env` را کپی و ویرایش کنید و اجرا کنید:

```bash
sudo sh simorgh-meet-0.2.0.run --answers answers.env
```

### پس از نصب

- اطلاعات ورود: `/opt/simorgh-meet/credentials.txt` (فقط root؛ پس از ذخیره در جای امن حذف کنید).
- در حالت self-signed فایل `/opt/simorgh-meet/simorgh-meet-ca.crt` را به‌عنوان Root CA مورد اعتماد روی رایانه‌ها و گوشی‌ها نصب کنید (GPO/MDM)؛ بدون آن مرورگر هشدار می‌دهد.
- فایروال: TCP 80 و 443 (یا پورت‌های انتخابی) و **UDP 10000**؛ با TURN: TCP/UDP 3478 و UDP 49160-49200.
- ساخت میزبان جدید (حالت internal):

```bash
sudo simorgh-meet user add reza
```

- **صورت‌جلسه خودکار:** میزبان در جلسه از منو «شروع رونویسی / زیرنویس» را می‌زند. پس از پایان جلسه، رونوشت دقیق‌شده و صورت‌جلسه در `/var/lib/simorgh-meet/minutes/<room>/<time>/` (`minutes.md`, `minutes.json`, `transcript.txt`) و در پایگاه داده (`meeting_minutes`, `action_items`) ذخیره می‌شود.

---

## ۵. مدیریت روزانه — `simorgh-meet`

| فرمان | کار |
|---|---|
| `simorgh-meet status` / `health` | وضعیت سرویس‌ها و بررسی سلامت همه اجزا |
| `simorgh-meet logs <service> [-f]` | لاگ‌ها |
| `simorgh-meet restart [service]` | راه‌اندازی مجدد |
| `simorgh-meet user add/del/passwd/list` | میزبان‌های جلسه (حالت internal) |
| `simorgh-meet backup [--with-recordings]` | پشتیبان پایگاه داده‌ها، تنظیمات، رونوشت‌ها و صورت‌جلسه‌ها |
| `simorgh-meet restore FILE [--yes]` | بازیابی |
| `simorgh-meet minutes list` / `minutes regenerate <meeting-id>` | فهرست / تولید دوباره صورت‌جلسه |
| `simorgh-meet glossary add <org-id> <واژه> [شکل معیار]` | واژه‌نامه سازمان (نام افراد، اصطلاحات، واژه‌های محلی) |
| `simorgh-meet maintenance` | اعمال مدت نگهداری ضبط‌ها و پاک‌سازی پشتیبان‌های قدیمی (روزانه با systemd timer) |
| `simorgh-meet upgrade /path/simorgh-meet-<new>.run` | پشتیبان‌گیری خودکار و سپس ارتقا با حفظ تنظیمات و رمزها |
| `simorgh-meet uninstall [--purge]` | حذف |

سرویس `simorgh-meet.service` استک را هنگام بوت بالا می‌آورد. فرمان `up` با `--pull never` اجرا می‌شود تا
سرور هرگز تلاش به دریافت از اینترنت نکند.

---

## ۶. آنچه در محیط آزمایش واقعاً اجرا و تأیید شد

نصب‌کننده واقعی روی Docker 29 با ایمیج‌های واقعی Jitsi/Keycloak/PostgreSQL و ایمیج‌های سیمرغ اجرا شد:

- نصب بدون تعامل، بارگذاری ایمیج‌ها، تولید CA و گواهی با SAN درست، بالا آمدن ۷ سرویس اصلی و سالم بودن همه.
- HTTPS با CA محلی، `/api/health/ready` از طریق nginx، مسدود بودن `/transcripts/`، ریدایرکت HTTP با حفظ پورت.
- واردشدن realm در Keycloak، کشف OIDC، دسترسی API به JWKS، پاسخ 401 بدون توکن.
- رابط کاربری فارسی، ورود میزبان با حساب ساخته‌شده توسط نصب‌کننده (مرورگر headless).
- **زنجیره کامل AI روی ترافیک واقعی Jitsi:** Jigasi به سرور STT ما وصل شد، صوت هر سخنران دریافت شد،
  رونوشت JSON جیتسی با نام واقعی سخنران تطبیق داده شد، مرحله refine روی صوت ذخیره‌شده اجرا شد، صورت‌جلسه و
  اقدام با مسئول عضو سازمان در PostgreSQL و فایل Markdown فارسی ذخیره شد. (در این محیط به‌جای مدل‌های واقعی از
  موتور mock و LLM ساختگی استفاده شد چون دانلود از HuggingFace مسدود بود؛ کیفیت مدل‌های واقعی باید روی صوت سازمان سنجیده شود.)
- پشتیبان‌گیری و بازیابی (بازگشت داده حذف‌شده)، نصب مجدد با حفظ رمزها، ساخت و تأیید فایل `.run` و تشخیص فایل خراب.

یافته‌های مهم که از همین آزمایش به محصول اضافه شد: Jigasi صوت را ۱۶ کیلوهرتز و در بسته‌های ۱٫۵ ثانیه‌ای می‌فرستد و
در سکوت بسته‌ای نمی‌فرستد (Opus DTX)؛ تشخیص مرز جمله بر اساس فاصله زمانی رسیدن بسته‌ها پیاده‌سازی شد.
نسخه پایدار جیتسی ذخیره JSON رونوشت را غیرفعال کرده بود که با یک اسکریپت init فعال شد.

---

## ۷. عیب‌یابی

| مشکل | راه‌حل |
|---|---|
| تصویر/صدا وصل نمی‌شود ولی صفحه باز می‌شود | UDP 10000 در فایروال؛ `JVB_ADVERTISE_IPS` در `/opt/simorgh-meet/.env` |
| هشدار گواهی در مرورگر | نصب `simorgh-meet-ca.crt` روی کلاینت یا استفاده از گواهی سازمان |
| ضبط شروع نمی‌شود | `simorgh-meet logs jibri`؛ هسته CPU و `/dev/shm` کافی |
| زیرنویس/رونویسی نمی‌آید | `simorgh-meet logs transcriber` و `logs stt`؛ پروفایل `ai` در `COMPOSE_PROFILES` |
| صورت‌جلسه ساخته نمی‌شود | `simorgh-meet logs ai-worker` و `logs llm`؛ جلسه کمتر از ۳۰ کلمه صورت‌جلسه ندارد |
| تغییر تنظیمات | ویرایش `/opt/simorgh-meet/.env` و سپس `simorgh-meet restart`، یا اجرای دوباره نصب‌کننده |

لاگ نصب: `/var/log/simorgh-meet-install.log`

---

## ۸. محدودیت‌های شناخته‌شده این نسخه

- پورتال وب سیمرغ (برنامه‌ریزی جلسه، دعوت‌نامه، تأیید صورت‌جلسه، تقویم) هنوز ساخته نشده است؛ جدول‌های پایگاه داده و
  سرویس AI آماده‌اند. وضعیت هر قابلیت در [FEATURE-MAP.md](FEATURE-MAP.md) آمده است.
- حالت احراز `jwt` به endpointهای صدور توکن جلسه در API نیاز دارد که هنوز پیاده نشده‌اند؛ تا آن زمان از `internal` استفاده کنید.
- فقط معماری x86_64 پشتیبانی می‌شود.


### دانلود رونویسی و صورت‌جلسه

میزبان در جلسه «رونویسی» را فعال می‌کند. پس از پایان جلسه و پردازش،
از دکمهٔ «دانلود متن و صورت‌جلسه» در صفحهٔ پایان تماس یا پیوند «بایگانی مدیر»
در صفحهٔ اصلی استفاده کنید. در پوشهٔ اتاق، نسخهٔ مربوط به زمان جلسه را باز کنید.

- `transcript.txt` متن فارسی استخراج‌شده از گفتار است.
- `minutes.md` صورت‌جلسهٔ تولیدشده است و با ویرایشگر متن باز می‌شود.
  برای جلساتی که متن کافی ندارند ممکن است فقط فایل رونویسی ساخته شود.

بایگانی شامل داده‌های همهٔ جلسات نصب است. نام کاربری مستقل `archive-admin`
و رمز اولیه در `/opt/simorgh-meet/archive-credentials.txt` قرار دارند.
این فایل فقط برای root قابل خواندن است. رمز بایگانی را جداگانه در محل امن نگه دارید.
