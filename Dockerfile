# OpsPilot API image.
#
# The fitted model is not built into the image: it is created by
# `python -m opspilot.modeling.train` and mounted at /app/models at run time
# (see the api service in compose.yaml).

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# XGBoost needs the OpenMP runtime on Linux.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml README.md ./
COPY src ./src
# Editable install: the code finds its SQL files relative to the source tree
# (/app/src -> /app/sql), which a regular install into site-packages would break.
# XGBoost's Linux package pulls in NVIDIA GPU libraries (about 350 MB) for
# multi-GPU training; the API only predicts on CPU, and predictions were
# checked to be identical without them, so they are removed.
RUN pip install -e ".[api]" \
    && pip list --format=freeze | grep -i '^nvidia-' | cut -d= -f1 | xargs -r pip uninstall -y

COPY sql ./sql
COPY reports/modeling ./reports/modeling

RUN useradd --create-home --uid 1000 opspilot
USER opspilot

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "opspilot.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
