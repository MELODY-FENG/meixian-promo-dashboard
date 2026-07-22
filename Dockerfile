FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py filter_opts.json templates/ ./templates/
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/* && \
    curl -fsSL -o /app/data.parquet "https://raw.githubusercontent.com/MELODY-FENG/meixian-promo-dashboard/master/data.parquet" && \
    ls -lh /app/data.parquet
EXPOSE $PORT
CMD gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2
