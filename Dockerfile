# syntax=docker/dockerfile:1
FROM python:3.9.5-slim

RUN apt-get update -y && apt-get install -y \
    build-essential tzdata make gcc
ENV TZ=Europe/Germany
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt requirements.txt
RUN python -m pip install numpy cython --no-binary numpy,cython && \
    python -m pip install -r requirements.txt && \
    python -m pip uninstall -y cython && \
    rm -r /root/.cache/pip && \
    apt-get remove -y --purge make gcc build-essential && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /code
CMD ["python", "/code/fundless/main.py"]