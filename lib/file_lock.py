"""
file_lock.py - 跨平台文件锁 + 原子写入

支持 Windows (msvcrt) 和 Unix (fcntl) 平台。
提供原子写入：先写临时文件，再 rename 到目标文件。
"""

import json
import os
import sys
import time
import tempfile
from pathlib import Path
from typing import Any, Optional

# 平台特定导入
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class TaskFileLock:
    """
    跨平台文件锁，支持原子读写 JSON 文件。

    使用方式:
        with TaskFileLock("Task.json") as lock:
            data = lock.read()
            data["tasks"][0]["status"] = "completed"
            lock.write(data)
    """

    def __init__(
        self,
        file_path: str,
        timeout: float = 5.0,
        retry_interval: float = 0.1,
    ):
        """
        初始化文件锁。

        Args:
            file_path: 要锁定的文件路径
            timeout: 获取锁的超时时间（秒）
            retry_interval: 重试间隔（秒）
        """
        self.file_path = Path(file_path).resolve()
        self.lock_path = self.file_path.with_suffix(self.file_path.suffix + ".lock")
        self.timeout = timeout
        self.retry_interval = retry_interval
        self._lock_file: Optional[Any] = None
        self._acquired = False

    def acquire(self) -> bool:
        """
        获取文件锁。

        Returns:
            是否成功获取锁

        Raises:
            TimeoutError: 超时未能获取锁
        """
        start_time = time.time()

        while True:
            try:
                # 创建或打开锁文件
                self._lock_file = open(self.lock_path, "w")

                if sys.platform == "win32":
                    # Windows: 使用 msvcrt.locking
                    msvcrt.locking(
                        self._lock_file.fileno(),
                        msvcrt.LK_NBLCK,
                        1
                    )
                else:
                    # Unix: 使用 fcntl.flock
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                self._acquired = True
                return True

            except (IOError, OSError):
                # 锁被占用，关闭文件句柄
                if self._lock_file:
                    self._lock_file.close()
                    self._lock_file = None

                # 检查超时
                elapsed = time.time() - start_time
                if elapsed >= self.timeout:
                    raise TimeoutError(
                        f"无法在 {self.timeout} 秒内获取文件锁: {self.lock_path}"
                    )

                # 等待后重试
                time.sleep(self.retry_interval)

    def release(self) -> None:
        """释放文件锁。"""
        if self._lock_file and self._acquired:
            try:
                if sys.platform == "win32":
                    msvcrt.locking(
                        self._lock_file.fileno(),
                        msvcrt.LK_UNLCK,
                        1
                    )
                else:
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            except (IOError, OSError):
                pass  # 忽略释放锁时的错误
            finally:
                self._lock_file.close()
                self._lock_file = None
                self._acquired = False

                # 尝试删除锁文件
                try:
                    self.lock_path.unlink()
                except (IOError, OSError):
                    pass

    def read(self) -> dict:
        """
        读取 JSON 文件内容。

        Returns:
            解析后的 JSON 数据

        Raises:
            FileNotFoundError: 文件不存在
            json.JSONDecodeError: JSON 格式错误
        """
        if not self._acquired:
            raise RuntimeError("必须先获取锁才能读取文件")

        with open(self.file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write(self, data: dict) -> None:
        """
        原子写入 JSON 文件。

        先写入临时文件，再 rename 到目标文件，确保原子性。

        Args:
            data: 要写入的数据
        """
        if not self._acquired:
            raise RuntimeError("必须先获取锁才能写入文件")

        # 获取目标文件所在目录
        target_dir = self.file_path.parent

        # 创建临时文件（在同一目录下，确保 rename 是原子的）
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix=self.file_path.stem + "_",
            dir=target_dir
        )

        try:
            # 写入临时文件
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # 原子替换（Windows 需要先删除目标文件）
            if sys.platform == "win32" and self.file_path.exists():
                self.file_path.unlink()

            os.rename(tmp_path, self.file_path)

        except Exception:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except (IOError, OSError):
                pass
            raise

    def __enter__(self) -> "TaskFileLock":
        """上下文管理器入口。"""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """上下文管理器出口。"""
        self.release()


def atomic_read_json(file_path: str) -> dict:
    """
    原子读取 JSON 文件（带锁）。

    Args:
        file_path: 文件路径

    Returns:
        解析后的 JSON 数据
    """
    with TaskFileLock(file_path) as lock:
        return lock.read()


def atomic_write_json(file_path: str, data: dict) -> None:
    """
    原子写入 JSON 文件（带锁）。

    Args:
        file_path: 文件路径
        data: 要写入的数据
    """
    with TaskFileLock(file_path) as lock:
        lock.write(data)


def atomic_update_json(file_path: str, updater: callable) -> dict:
    """
    原子更新 JSON 文件（读取-修改-写入）。

    Args:
        file_path: 文件路径
        updater: 更新函数，接收当前数据，返回更新后的数据

    Returns:
        更新后的数据
    """
    with TaskFileLock(file_path) as lock:
        data = lock.read()
        updated = updater(data)
        lock.write(updated)
        return updated
