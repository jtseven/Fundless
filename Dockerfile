# syntax=docker/dockerfile:1
FROM buster-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends build-essential tzdata
ENV TZ=Europe/Germany
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get install -y python3-pandas
COPY requirements.txt requirements.txt
RUN pip install -U pip
RUN pip install -r requirements.txt

WORKDIR /code
CMD ["python", "/code/fundless/main.py"]