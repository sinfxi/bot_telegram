FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*
ARG XRAY_VERSION=v26.7.28
RUN curl -fsSL "https://github.com/XTLS/Xray-core/releases/download/${XRAY_VERSION}/Xray-linux-64.zip" -o /tmp/xray.zip \
    && unzip -q /tmp/xray.zip xray -d /usr/local/bin \
    && chmod 0755 /usr/local/bin/xray \
    && /usr/local/bin/xray version \
    && rm -f /tmp/xray.zip
COPY requirements-xray.txt .
RUN pip install --no-cache-dir -r requirements-xray.txt
COPY xray_service.py .
RUN mkdir -p /data
EXPOSE 8080 8443 8444
CMD ["python", "xray_service.py"]
