FROM nginx:latest

RUN apt-get update && apt-get install -y python3 python3-dev python3-venv build-essential

RUN rm -rf /var/log/nginx && ln -s /app/logs /var/log/nginx
VOLUME /app/logs
EXPOSE 80
EXPOSE 443

WORKDIR /app

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip3 install --no-cache-dir -U flask flask_cors gunicorn dnspython UltraDict

COPY nginx/server.conf /etc/nginx/conf.d/server.conf
COPY nginx/headers.conf /etc/nginx/conf.d/headers.conf
COPY nginx/server.crt /app/certs/server.crt
COPY nginx/server.key /app/certs/server.key

ADD static /app/static
ADD templates /app/templates
COPY src/app.py /app/app.py
COPY src/utils.py /app/utils.py

CMD service nginx start && gunicorn --bind unix:/tmp/gunicorn.sock --preload --workers $(lscpu | egrep "^CPU\(s\):" | egrep -o [0-9]+) app:app
