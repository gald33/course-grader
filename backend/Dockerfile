FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       tesseract-ocr \
       tesseract-ocr-heb \
       poppler-utils \
       libmagic1 \
       fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Register the python3 Jupyter kernel so nbclient can execute notebooks
RUN python -m ipykernel install --name=python3 --display-name="Python 3" --sys-prefix

COPY . /app

# Make the google.colab stub importable so student notebooks can run
# `from google.colab import files` outside Colab without crashing.
ENV PYTHONPATH=/app/colab_stub

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
