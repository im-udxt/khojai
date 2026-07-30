FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user. The archive volume is chowned at build time.
RUN useradd --create-home --uid 10001 khoj \
 && mkdir -p /archive /models \
 && chown -R khoj:khoj /app /archive /models
USER khoj

CMD ["python", "-u", "main.py"]
