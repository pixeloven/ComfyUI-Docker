FROM bash:alpine3.22

RUN apk update && apk add parallel aria2

COPY . .
RUN chmod +x ./entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
