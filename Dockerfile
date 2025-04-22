FROM nikolaik/python-nodejs:python3.11-nodejs18-slim
RUN apt update \
    && apt full-upgrade -y \
    && apt install ffmpeg git gcc linux-libc-dev -y

COPY . /app/
WORKDIR /app/
RUN pip3 install --no-cache-dir wheel
RUN pip3 install --no-cache-dir -U pip -r requirements.txt
CMD ["python3", "-m", "hedoshi"]
