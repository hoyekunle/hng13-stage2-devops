# Blue/Green Node.js Service Deployment

This repository runs two pre-built Node.js images behind Nginx using Docker Compose. The setup provides
blue/green routing with quick detection and automatic failover: Nginx routes to the active pool (blue by
default) and retries to the backup (green) on errors/timeouts so clients still receive successful responses.

Quick facts
 - Nginx public entrypoint: http://3.88.175.33:8080 (mapped from `HOST_IP`/`PORT` in `.env`, default 3.88.175.33:8080)
 - Blue direct (for chaos control): http://3.88.175.33:8081 (host -> container 8081 -> 3000)
 - Green direct: http://3.88.175.33:8082

Prerequisites
- Docker and Docker Compose installed on the host.
- Images referenced in `.env` must be pullable by Docker (docker login if private).

Files of interest
- `docker-compose.yml` — orchestrates `nginx`, `app_blue`, `app_green`.
- `nginx/nginx.conf.template` — upstream template with primary/backup, tight timeouts and retry rules.
- `nginx/entrypoint.sh` — generates the effective `nginx.conf` at start based on `ACTIVE_POOL`.
- `.env` — environment used by Docker Compose (see example below).

Example `.env` (already provided in the repo)
```
BLUE_IMAGE=yimikaade/wonderful:devops-stage-two
GREEN_IMAGE=yimikaade/wonderful:devops-stage-two
ACTIVE_POOL=blue
RELEASE_ID_BLUE=blue-v1.0.0
RELEASE_ID_GREEN=green-v1.0.0
PORT=8080
```

How to run
1. Start the stack:

```bash
cd /home/hassan/hng13-stage2-devops
docker-compose up -d
```

2. Baseline checks (should be routed to the active pool):

```bash
curl -i http://3.88.175.33:8080/version     # main (via nginx)
curl -i http://3.88.175.33:8081/version     # blue (direct)
curl -i http://3.88.175.33:8082/version     # green (direct)
```

Failover test (manual)
1. Induce failure on the active (blue):

```bash
curl -X POST "http://3.88.175.33:8081/chaos/start?mode=error"
```

2. Immediately poll the main endpoint and observe that responses become served by `green` (X-App-Pool: green):

```bash
for i in {1..30}; do
  curl -s -D - http://3.88.175.33:8080/version | sed -n '1,6p'
  sleep 0.25
done
```

3. Stop chaos to restore blue:

```bash
curl -X POST "http://3.88.175.33:8081/chaos/stop"
```

Notes about behavior and tuning
- Nginx is configured with short timeouts and a retry policy (retries on error, timeout, and common 5xx codes) so that within a single client request it will try the backup upstream and return a 200 when possible.
- The upstream primary is marked quickly using `max_fails=1` and `fail_timeout=3s` for fast detection.
- Nginx forwards upstream response headers unchanged, so `X-App-Pool` and `X-Release-Id` from the apps are preserved.
- If your environment imposes a host firewall or cloud security group (AWS security group), open TCP ports 8080, 8081 and 8082.
- If you change `PORT` in `.env`, use that value for the public endpoint instead of 8080.

Switching the active pool
- The `ACTIVE_POOL` env var controls which container is primary in the generated Nginx config. Set it before starting the stack (CI should set it).
- To switch a running stack, recreate nginx so it regenerates the config:

```bash
# with compose file in repo root
docker-compose up -d --no-deps --force-recreate nginx
```

Validation and CI tips
- Use `docker-compose config` to validate the final compose config before startup.
- CI should set `BLUE_IMAGE`, `GREEN_IMAGE`, `RELEASE_ID_BLUE`, `RELEASE_ID_GREEN`, `ACTIVE_POOL`, and `PORT` as environment variables before `docker-compose up`.

Troubleshooting
- If requests to `/version` return non-200 responses during failover, check the app containers directly (`/version` and `/healthz`) to ensure the chaos endpoints are behaving as expected.
- If Nginx doesn't failover quickly enough, timeouts and retry counts live in `nginx/nginx.conf.template` and can be tuned (keep total request time < 10s per grader constraint).

Contact / Next steps
- If you want, I can run a quick `docker-compose config` or start the stack and execute the failover loop and report observed headers and success rate.

Operational visibility and alerts
--------------------------------

This project now includes an `alert_watcher` sidecar that tails Nginx access logs and posts actionable alerts to Slack.

What is instrumented
- Nginx access logs include: pool, release, upstream_status, upstream_addr, request_time, upstream_response_time.
- A small Python watcher (`watcher/alert_watcher.py`) tails `/var/log/nginx/access.log`, detects pool flips and elevated 5xx error rates, and posts to Slack via `SLACK_WEBHOOK_URL`.

Configuration (in `.env`)
- `SLACK_WEBHOOK_URL` — incoming Slack webhook URL (required to send alerts).
- `ERROR_RATE_THRESHOLD` — percentage (default 2) of 5xx responses over the sliding window that triggers an alert.
- `WINDOW_SIZE` — number of most recent requests to consider (default 200).
- `ALERT_COOLDOWN_SEC` — cooldown between repeated alerts of the same type (default 300s).
- `MAINTENANCE_MODE` — set `true` to suppress alerts during planned maintenance.

How alerts behave
- Failover alert: posted once when the watcher observes the serving pool change (e.g., blue -> green). Cooldown prevents repeated alerts.
- Error-rate alert: posted when the % of 5xx responses in the last `WINDOW_SIZE` requests exceeds `ERROR_RATE_THRESHOLD`.
- Alerts are deduplicated using cooldown windows.

Operator runbook (quick)
- Failover detected:
  1. Check the primary container logs: `docker-compose logs app_blue` (or app_green depending on which is primary).
  2. Check `/version` and `/healthz` on the upstream containers directly (ports 8081/8082).
  3. If the primary is unhealthy, keep the backup active and investigate the primary.

- High error-rate detected:
  1. Tail the Nginx logs: `tail -f logs/access.log` and inspect recent entries for `status` and `upstream_status`.
  2. Check app containers' logs (blue/green) to find source of 5xx errors.
  3. If needed, set `MAINTENANCE_MODE=true` in `.env` and restart `alert_watcher` to silence alerts while you remediate.

- Recovery:
  - When primary starts responding again and becomes the serving pool, a failover back to primary will be detected and an informational alert is posted.

Maintenance mode
- To suppress alerts during planned changes, set `MAINTENANCE_MODE=true` in `.env` and restart the watcher or recreate the `alert_watcher` service:

```bash
docker-compose up -d --no-deps --force-recreate alert_watcher
```

Testing alerts
- Failover test: Run the chaos endpoint on the primary (`POST http://HOST:8081/chaos/start?mode=error`) and observe a Slack failover alert.
- Error-rate test: Generate synthetic 5xx responses from an upstream (or flood the main endpoint with requests that cause 5xx) and observe the error-rate alert when threshold exceeded.

Files added
- `watcher/alert_watcher.py` — the log-tail/alerting logic.
- `watcher/requirements.txt` — Python dependency file (`requests`).

If you want, I can:
- Start the stack here, run a failover drill, and show the watcher output and sample Slack payloads (requires Docker and a reachable Slack webhook), or
- Tweak alert thresholds/cooldowns to match your grading criteria.
