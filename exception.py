# exceptions.py
class SpiderBaseException(Exception):
    """所有爬虫异常的基类"""
    def __init__(self, message: str, model_id: int = None):
        self.message  = message
        self.model_id = model_id
        super().__init__(message)

class FetcherNotFoundError(SpiderBaseException):
    """找不到对应采集器"""
    pass

class FetcherLoadError(SpiderBaseException):
    """采集器加载失败"""
    pass

class FetchError(SpiderBaseException):
    """采集过程中失败"""
    pass