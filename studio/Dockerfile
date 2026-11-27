FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY __init__.py api.py assistant.py compiler.py store.py service.py /srv/studio/
COPY web /srv/studio/web
ARG REVISION=unknown
LABEL org.opencontainers.image.revision=$REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1001
CMD ["python","-m","uvicorn","studio.api:app","--host","0.0.0.0","--port","8000","--no-access-log","--no-proxy-headers"]
