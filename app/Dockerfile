FROM python:3.13.0-slim-bullseye

WORKDIR /usr/src/app

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

RUN pip install --upgrade pip
COPY ./requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY ./entrypoint.sh .

COPY . .

ENTRYPOINT ["/usr/src/app/entrypoint.sh"]