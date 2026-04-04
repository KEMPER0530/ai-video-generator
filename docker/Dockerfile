FROM python:3.14-alpine

WORKDIR /work

COPY requirements.txt /tmp/requirements.txt

RUN apk add --no-cache ffmpeg bash curl fontconfig font-noto-cjk \
  && pip install --no-cache-dir -r /tmp/requirements.txt

ENTRYPOINT ["python3", "run.py"]
CMD ["--help"]
