FROM python:3.10

RUN pip install psutil
COPY reap.py /usr/local/bin
RUN chmod 555 /usr/local/bin/reap.py

ENTRYPOINT [ "/usr/local/bin/reap.py" ]
