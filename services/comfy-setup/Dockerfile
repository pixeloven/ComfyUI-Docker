FROM bash:alpine3.22

RUN apk update && apk add parallel aria2

COPY . .
RUN chmod +x ./entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]

# Create auto installer for https://github.com/cubiq/ComfyUI_IPAdapter_plus