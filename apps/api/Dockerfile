FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --create-home --uid 10001 app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN mkdir -p /app/var && chown -R app /app/var
USER app
EXPOSE 8400
CMD ["uvicorn", "aseo.main:app", "--host", "0.0.0.0", "--port", "8400", "--proxy-headers"]
