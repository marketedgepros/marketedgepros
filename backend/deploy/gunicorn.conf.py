"""Conservative production Gunicorn settings for MarketEdgePros."""

# Fixed loopback listener: deployment networking owns any external exposure.
bind = "127.0.0.1:5001"

# The application performs gevent/psycogreen monkey patching before use.
workers = 2
worker_class = "gevent"
worker_connections = 64
preload_app = False

timeout = 30
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 100

# Keep process and request logs on local standard streams; do not configure a
# remote provider or a file destination here.
accesslog = "-"
errorlog = "-"
capture_output = True
loglevel = "info"

# Connection budget: production configuration defaults each worker to
# pool_size=5 plus max_overflow=5. With two workers, the ceiling is 20 DB
# connections; this module intentionally does not initialize or alter that pool.
