import importlib
from exception import FetcherNotFoundError, FetcherLoadError
from fetchers.base_fetcher import BaseFetcher
from fetchers.naming import fetcher_class_name, normalize_fetcher_name

def load_fetcher(model_name: str, model_id: int, db_manager) -> BaseFetcher:
    model_name = normalize_fetcher_name(model_name)
    if not model_name:
        raise FetcherLoadError(
            "采集器模块名为空，请检查 reptile_model.m_reptile_model_script_address 是否已正确保存",
            model_id=model_id
        )

    module_path = f"fetchers.{model_name}.{model_name}_fetcher"
    class_name  = fetcher_class_name(model_name)

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        if e.name == module_path or (e.name and module_path.startswith(e.name)):
            raise FetcherNotFoundError(
                f"找不到采集器：{module_path}.py 不存在",
                model_id=model_id
            )
        raise FetcherLoadError(
            f"采集器 {module_path} 依赖模块缺失: {e}",
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
