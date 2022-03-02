# syntax=docker/dockerfile:1
FROM python:3.9-bullseye

# install essentials
RUN apt-get update -y && \
    apt-get install -y \
      build-essential \
      tzdata
ENV TZ=Europe/Berlin
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# setup dependencies for raspberry pi
ENV PIP_EXTRA_INDEX_URL="https://www.piwheels.org/simple"
RUN apt-get install -y libatlas3-base

# install dependencies
COPY requirements.txt requirements.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt && \
    rm -r /root/.cache/pip && \
    apt-get autoremove -y

WORKDIR /code
CMD ["python", "/code/fundless/__main__.py"]
