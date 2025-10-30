# Blue/Green Deployment Operator Runbook

This runbook provides detailed information about the alerting system, alert types, and required operator actions for the blue/green deployment setup.

## Alert System Overview

The system uses a Python-based alert watcher that monitors Nginx access logs and sends notifications to Slack when specific conditions are met. The watcher runs as a sidecar container (`alert_watcher`) alongside the main application containers.

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SLACK_WEBHOOK_URL` | required | Slack incoming webhook URL for sending alerts |
| `ERROR_RATE_THRESHOLD` | 2.0 | Percentage of 5xx responses that triggers an alert |
| `WINDOW_SIZE` | 200 | Number of most recent requests to consider for error rate calculation |
| `ALERT_COOLDOWN_SEC` | 300 | Minimum seconds between repeated alerts of the same type |
| `MAINTENANCE_MODE` | false | When true, suppresses all alerts during planned maintenance |

## Alert Types and Response Procedures

### 1. Failover Alert

**Trigger**: When the serving pool changes (e.g., blue → green or green → blue)

**Alert Format**:
```
🔄 Failover Detected
• From: [old_pool] → To: [new_pool]
• Release: [release_id]
• Upstream: [upstream_addr]
• Time: [UTC timestamp]
```

**Required Actions**:

1. Check the primary container logs:
   ```bash
   docker-compose logs app_blue   # if blue was primary
   # or
   docker-compose logs app_green  # if green was primary
   ```

2. Verify health endpoints on both pools:
   ```bash
   curl -i http://HOST:8081/healthz  # blue pool
   curl -i http://HOST:8082/healthz  # green pool
   ```

3. Check version endpoints to verify correct release IDs:
   ```bash
   curl -i http://HOST:8081/version  # blue pool
   curl -i http://HOST:8082/version  # green pool
   ```

4. Investigation checklist:
   - [ ] Check for CPU/memory pressure on the failed container
   - [ ] Review recent deployments or configuration changes
   - [ ] Verify network connectivity between containers
   - [ ] Check for any system-wide issues (disk space, network, etc.)

### 2. High Error Rate Alert

**Trigger**: When the percentage of 5xx errors exceeds `ERROR_RATE_THRESHOLD` in the last `WINDOW_SIZE` requests

**Alert Format**:
```
⚠️ High Error Rate Alert
• Rate: [X.X]% 5xx errors
• Window: last [N] requests
• Current Pool: [pool]
• Time: [UTC timestamp]
```

**Required Actions**:

1. Check real-time error rate:
   ```bash
   tail -f logs/access.log | grep -E "status=[5][0-9][0-9]"
   ```

2. Review application logs for both pools:
   ```bash
   docker-compose logs --tail=100 app_blue
   docker-compose logs --tail=100 app_green
   ```

3. Check system resources:
   ```bash
   docker stats app_blue app_green nginx
   ```

4. If needed, initiate manual failover:
   ```bash
   # To simulate errors on current primary:
   curl -X POST "http://HOST:8081/chaos/start?mode=error"
   # To stop chaos:
   curl -X POST "http://HOST:8081/chaos/stop"
   ```

## Maintenance Mode

### Enabling Maintenance Mode

When performing planned maintenance that might trigger alerts:

1. Set maintenance mode in `.env`:
   ```bash
   sed -i 's/MAINTENANCE_MODE=false/MAINTENANCE_MODE=true/' .env
   ```

2. Restart the alert watcher:
   ```bash
   docker-compose up -d --no-deps --force-recreate alert_watcher
   ```

### Disabling Maintenance Mode

After maintenance is complete:

1. Disable maintenance mode in `.env`:
   ```bash
   sed -i 's/MAINTENANCE_MODE=true/MAINTENANCE_MODE=false/' .env
   ```

2. Restart the alert watcher:
   ```bash
   docker-compose up -d --no-deps --force-recreate alert_watcher
   ```

## Troubleshooting

### Common Issues

1. **No alerts being received**:
   - Verify `SLACK_WEBHOOK_URL` is correct
   - Check alert_watcher logs: `docker-compose logs alert_watcher`
   - Ensure log file exists and is accessible: `/var/log/nginx/access.log`
   - Verify `MAINTENANCE_MODE` is not enabled

2. **Frequent failovers**:
   - Check network connectivity between containers
   - Review resource utilization
   - Verify timeout and retry settings in nginx.conf
   - Consider adjusting `max_fails` and `fail_timeout` in nginx config

3. **High error rates**:
   - Review application error logs
   - Check database connections if applicable
   - Verify external service dependencies
   - Consider scaling resources if under load

### Log Locations

- Nginx access logs: `./logs/access.log`
- Nginx error logs: `./logs/error.log`
- Container logs: Available via `docker-compose logs [service]`

## Testing Alert System

1. Test failover alerts:
   ```bash
   # Trigger errors on primary
   curl -X POST "http://HOST:8081/chaos/start?mode=error"
   # Wait for failover alert
   # Stop chaos
   curl -X POST "http://HOST:8081/chaos/stop"
   ```

2. Test error rate alerts:
   ```bash
   # Generate synthetic 5xx errors
   curl -X POST "http://HOST:8081/chaos/start?mode=error"
   # Make multiple requests to exceed threshold
   for i in {1..50}; do curl -s http://HOST:8080/version; done
   ```

## Contact Information

For issues with this alerting system, contact the DevOps team:
- Slack: #devops-alerts
- Email: devops@example.com