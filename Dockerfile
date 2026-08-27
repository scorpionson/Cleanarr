# Frontend build. react-scripts 5 needs a modern Node; this also retires the
# EOL node:12 stage.
FROM node:22-alpine AS build-stage

WORKDIR /frontend

COPY ./frontend /frontend

ENV REACT_APP_BACKEND_URL="/"

RUN yarn install && yarn build


# Runtime. Replaces tiangolo/uwsgi-nginx-flask, which its author archived.
FROM python:3.11-slim

ENV CONFIG_DIR="/config"
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY ./backend/requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY ./backend /app

# CRA emits static/ inside build/; the flattened copies keep both the
# /static/... and /static/static/... request paths resolvable, matching what
# nginx used to serve in the old base image.
COPY --from=build-stage /frontend/build /app/static
COPY --from=build-stage /frontend/build/static/css /app/static/css
COPY --from=build-stage /frontend/build/static/js /app/static/js

RUN mkdir -p $CONFIG_DIR

EXPOSE 80

# Let Docker tell a wedged container apart from a healthy one. /server/info is
# the cheapest endpoint that proves both Flask and the Plex connection work.
HEALTHCHECK --interval=60s --timeout=15s --start-period=30s --retries=3 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1/server/info', timeout=10).status==200 else 1)" || exit 1

# One worker on purpose: the ignore list is tinydb, which is not safe for
# concurrent writes from separate processes. Threads share a single instance.
# The long timeout is for full library scans, which routinely outlive any
# default worker timeout.
CMD ["gunicorn", "--bind", "0.0.0.0:80", \
     "--workers", "1", "--threads", "8", \
     "--timeout", "1800", "--graceful-timeout", "30", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "main:app"]
