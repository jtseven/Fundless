# syntax=docker/dockerfile:1
FROM python:3.9-alpine
WORKDIR /code

RUN apk add --no-cache gcc musl-dev linux-headers
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
CMD ["python", "/code/fundless/main.py"]