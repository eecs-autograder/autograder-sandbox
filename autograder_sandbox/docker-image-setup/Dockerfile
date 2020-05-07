FROM ubuntu:xenial

RUN apt-get update --fix-missing

RUN apt-get install -y g++
RUN apt-get install -y valgrind
RUN apt-get install -y clang
RUN apt-get install -y build-essential
RUN apt-get install -y python3
# Used in network access tests
RUN apt-get install -y iputils-ping

## Everything below this line is required for AutograderSandbox images to work properly.

RUN mkdir -p /home/autograder/working_dir

RUN useradd autograder && \
   mkdir -p /home/autograder/working_dir && \
   chown -R autograder:autograder /home/autograder

WORKDIR /home/autograder/working_dir
