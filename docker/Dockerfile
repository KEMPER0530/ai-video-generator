FROM python:3.11-alpine

WORKDIR /work

RUN apk add --no-cache ffmpeg bash curl fontconfig font-noto-cjk \
  && pip install --no-cache-dir gTTS==2.5.4

ENTRYPOINT ["python3", "run.py"]
CMD ["--help"]
