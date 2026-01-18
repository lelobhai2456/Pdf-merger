# Use a slim Python image for smaller size
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot code
COPY merge_pdfs_bot.py .

# Expose the port (Render will use $PORT, but we default to 8443 for webhooks)
EXPOSE 8443

# Run the bot
CMD ["python", "merge_pdfs_bot.py"]
