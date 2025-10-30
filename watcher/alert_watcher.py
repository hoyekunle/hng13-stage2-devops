#!/usr/bin/env python3
"""
Alert watcher for blue/green deployment.
Monitors Nginx access logs and alerts on:
1. Pool failovers (blue→green or green→blue)
2. High error rates (configurable threshold)
"""
import os
import re
import sys
import time
from collections import deque
from datetime import datetime

import requests

# Configuration from environment
LOG_PATH = '/var/log/nginx/access.log'
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')
ERROR_RATE_THRESHOLD = float(os.getenv('ERROR_RATE_THRESHOLD', '2.0'))
WINDOW_SIZE = int(os.getenv('WINDOW_SIZE', '200'))
ALERT_COOLDOWN_SEC = int(os.getenv('ALERT_COOLDOWN_SEC', '300'))
MAINTENANCE_MODE = os.getenv('MAINTENANCE_MODE', 'false').lower() in ('true', 'yes', '1')

# regex to capture key fields from our log format
RE_POOL = re.compile(r'pool=(?P<pool>[^\s]+)')
RE_RELEASE = re.compile(r'release=(?P<release>[^\s]+)')
RE_STATUS = re.compile(r'\s(?P<status>\d{3})\s')
RE_UPSTREAM_STATUS = re.compile(r'upstream_status=(?P<ustatus>[^\s]+)')
RE_UPSTREAM_ADDR = re.compile(r'upstream_addr=(?P<uaddr>[^\s]+)')
RE_REQUEST_TIME = re.compile(r'request_time=(?P<rt>[^\s]+)')

# state
last_seen_pool = None
rolling_statuses = deque(maxlen=WINDOW_SIZE)
last_alert_time = {'failover': 0, 'error_rate': 0}
last_release_by_pool = {}


def now_ts():
    return int(time.time())


def post_slack(message):
    if MAINTENANCE_MODE:
        print('Maintenance mode ON, suppressing alert:', message)
        return False
    if not SLACK_WEBHOOK_URL:
        print('No SLACK_WEBHOOK_URL configured, skipping alert:', message)
        return False
    payload = {'text': message}
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
        resp.raise_for_status()
        print('Posted alert to Slack')
        return True
    except Exception as e:
        print('Failed to post to Slack:', e)
        return False


def check_error_rate():
    if len(rolling_statuses) < 10:
        return None
    errors = sum(1 for s in rolling_statuses if 500 <= s < 600)
    rate = (errors / len(rolling_statuses)) * 100
    return rate


def handle_line(line):
    global last_seen_pool
    # extract fields
    pool_m = RE_POOL.search(line)
    release_m = RE_RELEASE.search(line)
    status_m = RE_STATUS.search(line)
    ustatus_m = RE_UPSTREAM_STATUS.search(line)
    uaddr_m = RE_UPSTREAM_ADDR.search(line)

    pool = pool_m.group('pool') if pool_m else 'unknown'
    release = release_m.group('release') if release_m else 'unknown'
    try:
        status = int(status_m.group('status')) if status_m else 0
    except Exception:
        status = 0
    upstream_status = ustatus_m.group('ustatus') if ustatus_m else ''
    upstream_addr = uaddr_m.group('uaddr') if uaddr_m else ''

    # update rolling window
    if WINDOW_SIZE > 0:
        rolling_statuses.append(status)

    # detect pool flip
    if last_seen_pool is None:
        last_seen_pool = pool
        last_release_by_pool[pool] = release
    elif pool != last_seen_pool:
        # pool flip detected
        t = now_ts()
        cooldown = last_alert_time.get('failover', 0)
        if t - cooldown >= ALERT_COOLDOWN_SEC:
            msg = (f"🔄 *Failover Detected*\n"
                   f"• From: {last_seen_pool} → To: {pool}\n"
                   f"• Release: {release}\n"
                   f"• Upstream: {upstream_addr}\n"
                   f"• Time: {datetime.utcnow().isoformat()}Z\n\n"
                   f"*Actions Required:*\n"
                   f"1. Check {last_seen_pool} container logs\n"
                   f"2. Verify health endpoints on both pools\n"
                   f"3. Investigate failover cause")
            posted = post_slack(msg)
            if posted:
                last_alert_time['failover'] = t
        else:
            print('Failover detected but in cooldown, skipping')
        last_seen_pool = pool
        last_release_by_pool[pool] = release

    # check error rate
    rate = check_error_rate()
    if rate is not None and rate >= ERROR_RATE_THRESHOLD:
        t = now_ts()
        if t - last_alert_time.get('error_rate', 0) >= ALERT_COOLDOWN_SEC:
            msg = (f"⚠️ *High Error Rate Alert*\n"
                   f"• Rate: {rate:.1f}% 5xx errors\n"
                   f"• Window: last {len(rolling_statuses)} requests\n"
                   f"• Current Pool: {last_seen_pool}\n"
                   f"• Time: {datetime.utcnow().isoformat()}Z\n\n"
                   f"*Actions Required:*\n"
                   f"1. Check application logs for errors\n"
                   f"2. Verify upstream health endpoints\n"
                   f"3. Consider manual failover if persistent\n"
                   f"4. Set MAINTENANCE_MODE=true if investigating")
            posted = post_slack(msg)
            if posted:
                last_alert_time['error_rate'] = t
        else:
            print('Error-rate alert in cooldown, skipping')


def follow(thefile):
    thefile.seek(0, 2)
    while True:
        line = thefile.readline()
        if not line:
            # check for rotation
            time.sleep(0.2)
            continue
        yield line


def open_and_follow(path):
    try:
        f = open(path, 'r', encoding='utf-8', errors='ignore')
    except FileNotFoundError:
        print('Log file not found, waiting for it to appear:', path)
        while True:
            time.sleep(1)
            if os.path.exists(path):
                f = open(path, 'r', encoding='utf-8', errors='ignore')
                break
    return f


def main():
    print('Starting alert_watcher, reading', LOG_PATH)
    f = open_and_follow(LOG_PATH)
    for line in follow(f):
        try:
            handle_line(line)
        except Exception as e:
            print('Error handling line:', e, file=sys.stderr)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Exiting')
        sys.exit(0)
