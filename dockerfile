FROM python:3.13-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r demo/server/requirements.txt

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "demo.server.main:app", "--host", "0.0.0.0", "--port", "8000"]