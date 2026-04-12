FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install uv for fast package management
RUN pip install uv

# Copy project configuration
COPY pyproject.toml .
# Copy lockfile if it exists, otherwise just the toml is fine
# COPY uv.lock . 

# Create virtual environment and install dependencies directly into the system python
RUN uv pip install --system -r pyproject.toml

# Copy application code
COPY . .

# Expose the port
EXPOSE 8080

# Run the FastAPI app with Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]