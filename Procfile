web: uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*' --ws-ping-interval 20 --ws-ping-timeout 20
