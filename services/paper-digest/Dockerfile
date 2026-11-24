FROM python:3.12.12-slim

# pandoc: doc.py builds the /doc Word file with it; fonts for the equation and diagram images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends pandoc fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY prompts/ ./prompts/

# Unprivileged user; the job only needs to read files and use the network.
RUN useradd --system --uid 10001 paper
# Writable state dir; a named volume mounted here inherits this owner.
RUN mkdir /app/state && chown 10001 /app/state
USER paper

CMD ["python", "-u", "digest.py"]
