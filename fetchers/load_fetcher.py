import importlib
from pathlib import Path
from exception import FetcherNotFoundError, FetcherLoadError
from fetchers.base_fetcher import BaseFetcher

def load_fetcher(model_name: str, model_id: int, db_manager) -> BaseFetcher:
    module_path = f"fetchers.{model_name}.{model_name}_fetcher"
    class_name  = f"{model_name.capitalize()}Fetcher"

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        raise FetcherNotFoundError(
            f"找不到采集器：{module_path}.py 不存在",
            model_id=model_id
        )

    cls = getattr(module, class_name, None)
    if cls is None:
        raise FetcherLoadError(
            f"模块 {module_path} 中找不到类 {class_name}，请检查类名是否符合约定",
            model_id=model_id
        )
    if not callable(cls):
        raise FetcherLoadError(
            f"{class_name} 不可调用，取到的是 {type(cls)}",
            model_id=model_id
        )

    return cls(model_id=model_id, db_manager=db_manager)  # type: ignore[return-value]