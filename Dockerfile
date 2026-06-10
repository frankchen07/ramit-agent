FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first — cached layer unless pyproject.toml changes
COPY pyproject.toml /app/
RUN pip install --no-cache-dir -e .

# Pre-download the embedding model so there's no cold-start delay
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Knowledge artifacts (90MB index — separate layer for cache efficiency)
COPY knowledge/output/ramit-sethi/ /app/knowledge/output/ramit-sethi/

# Persona and source code
COPY persona/ /app/persona/
COPY src/ /app/src/

CMD ["python", "-m", "src.bot"]
