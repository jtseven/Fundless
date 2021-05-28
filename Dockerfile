# syntax=docker/dockerfile:1
FROM python:3.9-buster
RUN apt-get update && apt-get install -y --no-install-recommends build-essential
RUN apt-get install -y python3-pandas python3-numpy

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

WORKDIR /code
CMD ["python", "/code/fundless/main.py"]