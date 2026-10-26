"""
本地缓存模块

数据获取有成本（AkShare 全市场快照约 1 分 15 秒），
缓存可以避免重复请求，加速后续选股流程。

缓存策略：
- 全市场快照：缓存 1 天（每日更新）
- 个股 K 线：缓存 1 天
- 财务数据：缓存 7 天
- 资金流：缓存 1 天
"""

import hashlib
import json
import logging
import pickle
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from config.settings import CACHE_DIR, DATA_SOURCE

logger = logging.getLogger(__name__)


class Cache:
    """本地文件缓存"""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = DATA_SOURCE["cache_ttl_days"] * 86400  # 秒

    def _key(self, *args, **kwargs) -> str:
        """生成缓存 key"""
        raw = json.dumps({"args": str(args), "kwargs": str(kwargs)}, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()

    def _path(self, key: str, ext: str = ".pkl") -> Path:
        return self.cache_dir / f"{key}{ext}"

    def get(self, key: str, ttl: Optional[float] = None) -> Optional[object]:
        """
        读取缓存

        Args:
            key: 缓存 key
            ttl: 过期时间（秒），None 则用默认

        Returns:
            缓存对象或 None（不存在/过期）
        """
        path = self._path(key)
        if not path.exists():
            return None

        try:
            age = (datetime.now().timestamp() - path.stat().st_mtime)
            if ttl is None:
                ttl = self.ttl
            if age > ttl:
                logger.debug(f"缓存过期: {key} (age={age:.0f}s)")
                return None

            with open(path, "rb") as f:
                data = pickle.load(f)
            logger.debug(f"缓存命中: {key}")
            return data
        except Exception as e:
            logger.warning(f"缓存读取失败 {key}: {e}")
            return None

    def set(self, key: str, data: object, ttl: Optional[float] = None) -> None:
        """写入缓存"""
        path = self._path(key)
        try:
            with open(path, "wb") as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
            logger.debug(f"缓存写入: {key}")
        except Exception as e:
            logger.warning(f"缓存写入失败 {key}: {e}")

    def get_json(self, key: str) -> Optional[object]:
        """读取 JSON 缓存"""
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def set_json(self, key: str, data: object) -> None:
        """写入 JSON 缓存"""
        path = self.cache_dir / f"{key}.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.warning(f"JSON缓存写入失败 {key}: {e}")

    def clear(self) -> None:
        """清空缓存"""
        import shutil
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("缓存已清空")


# 全局实例
cache = Cache()
