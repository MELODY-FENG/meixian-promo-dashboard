FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
COPY app.py filter_opts.json templates/ ./templates/
COPY . .
RUN curl -L -o /app/data.parquet "https://raw.githubusercontent.com/MELODY-FENG/meixian-promo-dashboard/master/data.parquet?token=$(curl -s https://api.github.com/repos/MELODY-FENG/meixian-promo-dashboard/contents/data.parquet | python3 -c 'import sys,json; print(json.load(sys.stdin).get("download_url",""))')" || echo "Download will happen at runtime"
EXPOSE $PORT
CMD gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2
