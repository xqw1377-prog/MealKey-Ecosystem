"""pytest 全局配置。

测试环境强制关闭所有 LLM 调用，避免测试时发起真实网络请求导致超时。
- MEALKY_AGENT_LLM=0：关闭 narrator
- MEALKY_DIAGNOSIS_LLM=0：关闭 LLM 诊断推理器
生产环境通过 .env 开启。
"""

import os

# 必须在所有 app 模块 import 之前设置
os.environ["MEALKY_AGENT_LLM"] = "0"
os.environ["MEALKY_DIAGNOSIS_LLM"] = "0"
os.environ["MEALKEY_DISABLE_CLOCK"] = "1"
