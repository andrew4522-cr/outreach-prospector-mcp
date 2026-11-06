FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY outreach_prospector_mcp ./outreach_prospector_mcp

RUN pip install --no-cache-dir -e .

ENTRYPOINT ["outreach-prospector-mcp"]
