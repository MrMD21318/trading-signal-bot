FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tv_bridge/package.json tv_bridge/
WORKDIR /app/tv_bridge
RUN npm install --omit=dev

WORKDIR /app
COPY . .

ENV SMC_CREDIT=0
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python", "run.py"]
