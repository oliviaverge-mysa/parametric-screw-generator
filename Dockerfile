FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 \
    gcc g++ pkg-config libcairo2-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

COPY --chown=user src/ src/
COPY --chown=user web/ web/
COPY --chown=user run_web.py .

RUN python -c "import base64,pathlib; f=pathlib.Path('web/brand-bg.b64'); p=pathlib.Path('web/brand-bg.png'); b=f.read_text().split(',',1)[1] if ',' in f.read_text() else f.read_text(); p.write_bytes(base64.b64decode(b))" 2>/dev/null || true

RUN mkdir -p $HOME/app/out

ENV HOST=0.0.0.0
ENV PORT=7860

EXPOSE 7860

CMD ["python", "run_web.py"]
