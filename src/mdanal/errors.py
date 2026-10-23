"""异常类型。每个异常都带 where，指出出错的文件与键，便于直接定位。"""


class MdanalError(Exception):
    """运行期错误的基类。"""

    def __init__(self, message: str, where: str | None = None):
        self.message = message
        self.where = where
        super().__init__(f"{where}：{message}" if where else message)


class UsageError(MdanalError):
    """命令行用法错误。"""


class ValidationError(MdanalError):
    """输入校验错误：文件、分组、槽位、参数、依赖。"""
