FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies needed for testing
RUN apt-get update && apt-get install -y \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements files
COPY requirements.txt /app/tests/requirements.txt
COPY runner-requirements.txt /app/tests/runner-requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir \
    -r /app/tests/requirements.txt \
    -r /app/tests/runner-requirements.txt

# Copy test files and runners
COPY . /app/tests/

# Set executable permissions
RUN chmod +x /app/tests/test_runner.py /app/tests/test_containerized.sh

# Set environment variables
ENV PYTHONPATH=/app
ENV PROJECT_ROOT=/workspace

# Default command
ENTRYPOINT ["python3", "/app/tests/test_runner.py"]
CMD ["all"]
