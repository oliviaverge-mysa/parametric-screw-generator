FROM continuumio/miniconda3:latest

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

RUN conda install -y -c conda-forge cadquery=2.4 && conda clean -afy

COPY requirements-pip.txt /tmp/requirements-pip.txt
RUN pip install --no-cache-dir -r /tmp/requirements-pip.txt && rm /tmp/requirements-pip.txt

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

COPY --chown=user src/ src/
COPY --chown=user web/ web/
COPY --chown=user run_web.py .

RUN mkdir -p $HOME/app/out

ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["python", "run_web.py"]
