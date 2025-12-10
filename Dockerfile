FROM python:3.11-slim

WORKDIR /app

# Install git for update functionality
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application (will be overridden by volume mount in development)
COPY . .

# Create upload directory
RUN mkdir -p uploads

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production

# Expose port
EXPOSE 8081

# Run with reload enabled so updates take effect automatically
CMD ["gunicorn", "--bind", "0.0.0.0:8081", "--workers", "2", "--reload", "app:app"]
