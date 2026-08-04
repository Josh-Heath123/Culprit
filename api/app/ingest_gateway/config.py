import os

INGEST_GATEWAY_DATABASE_URL = os.environ["INGEST_GATEWAY_DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
