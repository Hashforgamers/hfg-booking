FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 5054 9181 9182

CMD sh -c "rq worker --url $REDIS_URL booking_tasks & \
           rq-dashboard --redis-url $REDIS_URL --port 9181 & \
           (while true; do rqscheduler --url $REDIS_URL --interval 60; echo 'rqscheduler crashed, restarting in 5s'; sleep 5; done) & \
           exec gunicorn -k eventlet -w 1 'app:app' -b 0.0.0.0:5054 --timeout 120"
