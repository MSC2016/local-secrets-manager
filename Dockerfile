FROM python:3.14.4-slim-bookworm

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY docs ./docs
COPY scripts ./scripts
COPY gunicorn_conf.py ./gunicorn_conf.py
COPY main.py ./main.py

ENV APP_HOST=0.0.0.0
ENV APP_PORT=5000
ENV APP_DATA_DIR=/app/data

EXPOSE 5000

CMD ["gunicorn", "--config", "gunicorn_conf.py", "app.main:create_app()"]
