FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY calendar_api.py server.py ./

# Run as an unprivileged user; the server needs no write access anywhere.
RUN useradd --system --uid 10001 mcp
USER mcp

EXPOSE 8000
CMD ["python", "server.py"]
