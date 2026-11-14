FROM pgvector/pgvector:pg18

# 安装编译 pg_jieba 所需依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    ca-certificates \
    postgresql-server-dev-18 \
    && rm -rf /var/lib/apt/lists/*

# 从源码克隆并编译安装 pg_jieba
RUN INC=$(pg_config --includedir-server) \
    && git clone --recursive https://github.com/jaiminpan/pg_jieba.git /tmp/pg_jieba \
    && cd /tmp/pg_jieba \
    && mkdir build && cd build \
    && cmake -DPostgreSQL_TYPE_INCLUDE_DIR=${INC} -DCMAKE_BUILD_TYPE=Release .. \
    && make \
    && make install \
    && rm -rf /tmp/pg_jieba

# 清理编译依赖，保持镜像精简
RUN apt-get purge -y \
    build-essential \
    cmake \
    git \
    postgresql-server-dev-18 \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
