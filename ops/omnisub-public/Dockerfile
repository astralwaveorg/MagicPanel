FROM python:3.13-slim
WORKDIR /app
RUN pip install --disable-pip-version-check --no-cache-dir Flask==3.1.3 gunicorn==25.1.0 PyYAML==6.0.3 cryptography==50.0.2
COPY app.py .
COPY www ./www
ENV PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
CMD ["gunicorn","--bind","0.0.0.0:8000","--workers","3","--timeout","40","--limit-request-line","8190","--error-logfile","/dev/null","app:app"]
