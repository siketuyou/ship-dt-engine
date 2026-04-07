# 在项目根目录新建 download_model.py 运行一次就行
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    local_dir="./models/paraphrase-multilingual-MiniLM-L12-v2",
)
print("下载完成")# 在项目根目录新建 download_model.py 运行一次就行
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    local_dir="./models/paraphrase-multilingual-MiniLM-L12-v2",
)
print("下载完成")