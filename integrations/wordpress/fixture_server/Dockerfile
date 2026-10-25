# WordPress companion-plugin TEST FIXTURE (not WordPress). Demo/staging only.
FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.12 "uvicorn[standard]==0.34.2"
WORKDIR /fixture
COPY server.py .
RUN useradd --uid 10001 app
USER app
ENV WP_FIXTURE_HOST=0.0.0.0
CMD ["python", "server.py"]
