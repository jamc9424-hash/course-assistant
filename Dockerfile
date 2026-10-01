FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# LibreOffice enables automatic PPT/PPTX/ODP-to-PDF rendering for slide images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-impress \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-optional.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-optional.txt
COPY src ./src
COPY README.md .env.example ./
RUN pip install --no-cache-dir -e .

EXPOSE 7860
CMD ["python", "-m", "course_assistant.app"]
