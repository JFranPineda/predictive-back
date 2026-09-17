FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# weasyprint (PDF reports) and pillow-heif need these
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev libheif1 libde265-0 \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libffi-dev \
    exiftool \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"
COPY . .

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
