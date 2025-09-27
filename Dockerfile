FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 5054 9181 9182

# Run Gunicorn with Eventlet worker + RQ + RQ dashboard + scheduler
CMD sh -c "\
    gunicorn -k eventlet -w 1 app:app -b 0.0.0.0:5054 & \
    rq worker --url $REDIS_URL booking_tasks & \
    rq-dashboard --redis-url $REDIS_URL --port 9181 & \
    rqscheduler --url $REDIS_URL --interval 60"
