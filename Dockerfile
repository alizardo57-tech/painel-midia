FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .
ENV PORT=5000
ENV DATA_DIR=/app/data
EXPOSE 5000

CMD ["sh", "-c", "gunicorn -w 2 --threads 4 -b 0.0.0.0:${PORT:-5000} app:app"]
