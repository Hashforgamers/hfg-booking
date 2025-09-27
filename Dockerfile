FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /app

# Expose ports
EXPOSE 5054 9181 9182

# Use Gunicorn with Eventlet (or GeventWebSocket) worker
CMD sh -c "\
    gunicorn -k eventlet -w 1 app:app -b 0.0.0.0:5054 & \
    rq worker --url $REDIS_URL booking_tasks & \
    rq-dashboard --redis-url $REDIS_URL --port 9181 & \
    rqscheduler --url $REDIS_URL --interval 60"
