# https://hub.docker.com/_/python
FROM python:3.8

ENV PYTHONUNBUFFERED True

# Copy local code to the container image.
ENV APP_HOME /app
ENV PORT 5000

WORKDIR $APP_HOME
COPY . ./

# install rust
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install production dependencies.
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE $PORT

# Using Debian, as root
RUN curl -fsSL https://deb.nodesource.com/setup_17.x | bash -
RUN apt-get install -y nodejs

CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app