"""Bounded starting configuration; validate against the deployed rehearsal workload."""

import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("WEB_CONCURRENCY", "3"))
worker_class = "sync"
timeout = 60
graceful_timeout = 30
keepalive = 5
max_requests = 2000
max_requests_jitter = 200
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190
# Log the path without query strings, cookies, Authorization or request bodies.
accesslog = "-"
access_log_format = '%(t)s "%(m)s %(U)s" %(s)s %(L)s request_id=%({x-request-id}o)s'
errorlog = "-"
loglevel = "info"
capture_output = True
