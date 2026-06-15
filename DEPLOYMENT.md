# Running 24/7 (even when your laptop is off)

A powered-off laptop can't run anything, so "always on" means running the
monitor on a host that stays on. This guide covers the realistic options.

> **Key simplification:** with the **Telegram** channel configured, the monitor
> can run in `NOTIFY_MODE=telegram_only` and **drop the cloudflared tunnel and
> media server entirely** — Telegram uploads the frame images directly. That
> makes headless hosts (Pi, cloud VM, NAS) much simpler. All deployment options
> below assume `telegram_only`.

## Options at a glance

| Host | Cost | Effort | Best for |
| --- | --- | --- | --- |
| Spare laptop/desktop left on | Free | Low | Easiest if you have spare hardware |
| **Raspberry Pi / mini PC** | ~$50–120 once | Medium | **Recommended** set-and-forget, ~2 W |
| Cloud VM (Oracle Always-Free, AWS, Azure) | Free–$5/mo | Medium | No home hardware |
| NAS via Docker | Owned | Medium | If you already run a NAS |

Two things must travel to any non-Windows host:
1. **The patched blinkpy fork** — already built into `vendor/blinkpy-*.whl`
   (the PyPI version does NOT handle Blink's current 2FA flow).
2. **A logged-in `blink_creds.json`** — do the one-time 2FA login on your
   desktop (`python -m src.setup_2fa`), then copy that file to the host.

---

## A) Docker (most portable — Pi, cloud VM, or NAS)

One image runs anywhere Docker does. Files provided: `Dockerfile`,
`docker-compose.yml`, `.dockerignore`, `requirements-docker.txt`.

```bash
# On the always-on host (with Docker + Docker Compose installed):
git clone <your-repo> blink-whatsapp   # or copy the folder over
cd blink-whatsapp

# 1. Put your .env here (with Telegram creds filled in) and the cached login:
#    - .env                (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TWILIO_*, GITHUB_TOKEN)
#    - blink_creds.json    (created by `python -m src.setup_2fa` on your desktop)

# 2. Build and start (restarts on crash + at boot automatically):
docker compose up -d --build

# 3. Watch it:
docker compose logs -f
```

- The image installs **system ffmpeg** (multi-arch: works on Pi arm64 and x86).
- `restart: unless-stopped` keeps it running across reboots and crashes.
- `blink_creds.json` and `frames/` are mounted as volumes so the session
  persists and you can inspect captured frames.
- Builds for a Raspberry Pi work the same; Docker pulls the arm64 base image.

---

## B) Raspberry Pi / Linux without Docker (systemd)

```bash
sudo apt update && sudo apt install -y python3-venv ffmpeg
git clone <your-repo> ~/blink-whatsapp && cd ~/blink-whatsapp
python3 -m venv .venv
.venv/bin/pip install -r requirements-docker.txt
.venv/bin/pip install --no-deps vendor/blinkpy-*.whl

# Copy your .env and blink_creds.json into ~/blink-whatsapp, then install the
# service (edit User/paths inside the unit first):
sudo cp deploy/blink-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now blink-monitor
journalctl -u blink-monitor -f        # live logs
```

`Restart=always` restarts on crash; `enable` starts it at boot. This is the
Linux equivalent of the Windows scheduled task.

---

## C) Cloud VM (no home hardware)

Any small Linux VM works. Good free/cheap choices:

- **Oracle Cloud Always-Free** — genuinely free Arm/x86 VM, no time limit.
- **AWS EC2 t4g.nano / Azure B1s** — a few $/month (or free tier for 12 months).

Steps: create an Ubuntu VM, then follow **A) Docker** or **B) systemd** exactly
as above. Upload `.env` and `blink_creds.json` securely (e.g. `scp`). No inbound
ports are needed because Telegram is outbound-only and there is no tunnel.

> Note: cloud VMs are remote, so they reach Blink's cloud fine, but they obey
> the same Blink account/2FA. If Blink forces re-auth, re-run `setup_2fa` on a
> desktop and re-copy `blink_creds.json`.

---

## D) Keep the Windows laptop on (no migration)

If you don't want new hardware yet, just don't shut down. Use the existing
Windows path:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_service.ps1
Start-ScheduledTask -TaskName BlinkWhatsAppMonitor
```

Then disable sleep/hibernate (Settings → Power, or `powercfg /change
standby-timeout-ac 0`). This is not "after shutdown" — the machine must stay on.

---

## Recommendation

- **Cheapest set-and-forget:** a **Raspberry Pi** running the Docker image (A) or
  systemd service (B). Silent, ~2 W, lives by your router.
- **No hardware:** an **Oracle Always-Free** VM with the Docker image.
- Either way, set `NOTIFY_MODE=telegram_only` (default in the container) so you
  don't depend on the ephemeral cloudflared tunnel. Add `whatsapp` back via
  `both`/`whatsapp_first` only if you also expose a public media URL.

## Updating the bundled blinkpy fork

If you patch blinkpy again locally, rebuild the vendored wheel:

```powershell
python -m pip wheel C:\personal\coding\blink\blinkpy --no-deps -w vendor
```

then rebuild the image / reinstall in the venv.
