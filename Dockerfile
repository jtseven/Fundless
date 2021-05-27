# syntax=docker/dockerfile:1
FROM python:3.9-buster
WORKDIR /code
RUN apt-get update && apt-get install -y --no-install-recommends build-essential
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
CMD ["python", "/code/fundless/main.py"]