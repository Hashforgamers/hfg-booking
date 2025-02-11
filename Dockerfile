# Use official Python image from DockerHub
FROM python:3.10-slim

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV REDIS_URL=redis://red-culflulds78s73bqveqg:6379

# Install dependencies
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install rq and rq-scheduler separately
RUN pip install rq rq-scheduler redis[rq]

# Copy the application code
COPY . /app

# Expose ports
EXPOSE 5053 9182

# Start Flask app, RQ worker, and RQ dashboard in a single container
CMD ["sh", "-c", "python app.py & rq worker --url $REDIS_URL booking_tasks & rq-scheduler --url $REDIS_URL & rqscheduler --interval 60 & rq-dashboard --redis-url $REDIS_URL --port 9181"]
