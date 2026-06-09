FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt package.json ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && npm install

COPY . .
RUN npm run build

EXPOSE 2236

CMD ["python", "main.py", "dashboard", "--config", "config.example.toml", "--host", "0.0.0.0", "--workspace", "/workspace"]
