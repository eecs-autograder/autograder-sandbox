FROM phusion/baseimage:latest

RUN apt-get update --fix-missing

RUN apt-get install -y g++
RUN apt-get install -y valgrind
RUN apt-get install -y clang
RUN apt-get install -y build-essential
RUN apt-get install -y python3
RUN apt-get install -y iputils-ping

RUN mkdir -p /home/autograder/working_dir

RUN useradd autograder && \
   mkdir -p /home/autograder/working_dir && \
   chown -R autograder:autograder /home/autograder

COPY cmd_runner.py /usr/local/bin/cmd_runner.py
RUN chmod 555 /usr/local/bin/cmd_runner.py

WORKDIR /home/autograder/working_dir

