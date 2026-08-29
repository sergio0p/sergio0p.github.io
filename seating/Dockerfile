# Build context is seating/ -- the container needs both the service and the app
# files it serves, and those live side by side in this directory.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv

COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

# Only what is served or does the serving. tools/, reference/, data/room-photos
# and the plans are deliberately absent from the image.
COPY server/main.py       server/main.py
COPY index.html           index.html
COPY style.css            style.css
COPY js/                  js/
COPY assets/              assets/
COPY data/room-layout.json data/room-layout.json

# The problem-set pages, and the answer keys they are graded against. The keys
# are reachable only through /api/ps/<ps>/key, which refuses until the due date;
# the static route serving this directory rejects .json outright, so shipping
# them here does not expose them.
COPY ps/                  ps/

ENV PORT=8080
EXPOSE 8080
CMD exec gunicorn --bind :$PORT --workers 2 --threads 8 --timeout 30 \
    --chdir /srv server.main:app
