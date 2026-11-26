FROM python:3.12-slim
WORKDIR /srv/backend
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 FASTEMBED_CACHE_PATH=/models
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/eval ./eval
RUN pip install .
COPY data /srv/data
ENV DATA_DIR=/srv/data
EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
