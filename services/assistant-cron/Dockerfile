FROM python:3.12.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY briefing.py ./

# Unprivileged user; the job only needs to read files and use the network.
RUN useradd --system --uid 10001 cron
USER cron

CMD ["python", "-u", "briefing.py"]
