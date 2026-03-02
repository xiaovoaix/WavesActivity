import sys
from pathlib import Path

from gsuid_core.data_store import get_res_path

MAIN_PATH = get_res_path() / "WavesActivity"
sys.path.append(str(MAIN_PATH))

# 配置文件
CONFIG_PATH = MAIN_PATH / "config.json"

# 状态文件
STATUS_PATH = MAIN_PATH / "status.json"


def init_dir():
    MAIN_PATH.mkdir(parents=True, exist_ok=True)


init_dir()
