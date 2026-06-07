"""
公共清洗库
----------
本包自动将 lib/ 目录加入 sys.path，使 D2-D6 脚本无需修改即可导入:
  from advanced_cleaning import TimePipeline, PrivacyMasker, ...
"""

import sys
from pathlib import Path

# 将 lib/ 目录加入 sys.path (仅在 import 时执行一次)
_lib_dir = Path(__file__).resolve().parent
_lib_dir_str = str(_lib_dir)
if _lib_dir_str not in sys.path:
    sys.path.insert(0, _lib_dir_str)

# 自动导出常用类
try:
    from advanced_cleaning import (
        TimePipeline,
        PrivacyMasker,
        SensitiveFilter,
        SimHashDedup,
        CleaningReport,
    )
    __all__ = [
        "TimePipeline",
        "PrivacyMasker",
        "SensitiveFilter",
        "SimHashDedup",
        "CleaningReport",
    ]
except ImportError:
    pass
