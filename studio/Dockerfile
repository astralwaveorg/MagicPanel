FROM node:24-alpine@sha256:116b800c3754b440ee0aa3ed2f20f5bf3d99a554bfd9adeea09ea8017f6e85f5 AS frontend
WORKDIR /ui
COPY client/package*.json ./
RUN npm ci --no-audit --no-fund
COPY client/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY *.py /srv/studio/
COPY ops/platform_upgrade.py /srv/studio/platform_upgrade.py
COPY --from=frontend /ui/dist /srv/studio/web
ARG REVISION=unknown
LABEL org.opencontainers.image.revision=$REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1001
CMD ["python","-m","uvicorn","studio.api:app","--host","0.0.0.0","--port","8000","--no-access-log","--no-proxy-headers"]
