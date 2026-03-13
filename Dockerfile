FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared library
COPY shared/ /app/shared/

# Copy application code
COPY app/ /app/app/

# Copy migrations + config
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

# Create non-root user
RUN useradd -m -u 1000 appuser
USER appuser

EXPOSE 8007

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8007"]
