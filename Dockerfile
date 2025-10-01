FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 5054 9181 9182

CMD sh -c "gunicorn -k eventlet -w 1 'app:create_app' -b 0.0.0.0:5054 --timeout 120 & \
           rq worker --url $REDIS_URL booking_tasks & \
           rq-dashboard --redis-url $REDIS_URL --port 9181 & \
           rqscheduler --url $REDIS_URL --interval 60"
