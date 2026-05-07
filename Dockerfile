FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（pymysql / sentence-transformers 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 预建目录，避免运行时因挂载卷顺序问题导致权限错误
RUN mkdir -p data/output data/upload

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
