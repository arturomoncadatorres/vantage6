# poc that we can dockerize the node-instance
FROM ppdli-base


COPY . /joey
RUN pip install /joey

# copy all files to app folder
COPY /joey/node/start.py /app/start.py

# expose the proxy server port
ARG port=80
EXPOSE ${port}
ENV PROXY_SERVER_PORT ${port}

# create entrypoint
ENTRYPOINT [ "python", "/app/start.py"]