FROM python:3.11-slim

RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860 \
    PYTHONUNBUFFERED=1

WORKDIR /home/user/app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        torch \
        "diffusers>=0.30.0" \
        "transformers>=4.44.0" \
        "accelerate>=0.33.0" \
        "gradio>=4.44.0" \
        safetensors \
        opencv-python-headless \
        numpy \
        pillow

COPY --chown=user app.py /home/user/app/app.py

USER user

EXPOSE 7860

CMD ["python", "app.py"]
