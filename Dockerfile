FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Optional: create temp folder (though your code already does mkdir)
RUN mkdir -p pdf_temp

# Use shell form so $PORT expands correctly
CMD gunicorn --bind 0.0.0.0:${PORT:-10000} app:app --log-level info
