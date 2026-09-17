# Imagem única: serve o painel (Streamlit) e também roda o pipeline.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

WORKDIR /srv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --group app

COPY app ./app
COPY .streamlit ./.streamlit

ENV PATH="/srv/.venv/bin:$PATH" \
    ANS_LAKE_URI=/data/lake \
    ANS_GOLD_URI=/data/lake/gold \
    ANS_WORK_DIR=/data/work

RUN useradd --create-home --uid 1000 ans && mkdir -p /data && chown ans /data
USER ans

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
