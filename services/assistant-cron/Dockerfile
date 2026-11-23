FROM python:3.12.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY briefing.py reminders.py rain.py news.py markets.py spoken.py ./

# Unprivileged user; the job only needs to read files and use the network.
RUN useradd --system --uid 10001 cron
# Writable state dir; a named volume mounted here inherits this owner.
RUN mkdir /app/state && chown 10001 /app/state
USER cron

CMD ["python", "-u", "briefing.py"]
