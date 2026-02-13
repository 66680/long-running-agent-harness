"""
intake_handler.py - Intake 核心处理逻辑

处理 inbox/REQ_*.md 需求单：
1. 解析需求单
2. 合并项目要求到 CLAUDE.md
3. 合并运行参数到 Task.json config
4. 转换 Task Seeds 为可执行任务
5. 运行门禁校验
6. git commit
"""

import json
import os
import re
import shutil
import subprocess
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .file_lock import TaskFileLock
from .state_machine import TaskStateMachine
from .progress_logger import ProgressLogger


class IntakeHandler:
    """
    Intake 处理器。

    处理 inbox/REQ_*.md 需求单，自动完成：
    - 解析需求单
    - 合并项目要求到 CLAUDE.md
    - 合并运行参数到 Task.json config
    - 转换 Task Seeds 为可执行任务
    - 运行门禁校验
    - git commit
    """

    def __init__(self, inbox_dir: str, config: dict):
        """
        初始化 Intake 处理器。

        Args:
            inbox_dir: inbox 目录路径
            config: 配置字典
        """
        self.inbox_dir = Path(inbox_dir).resolve()
        self.processed_dir = self.inbox_dir / "processed"
        self.config = config
        self.logger = ProgressLogger(config.get("progress_file", "progress.txt"))
        self.state_machine = TaskStateMachine({
            "lease_ttl_seconds": config.get("lease_ttl_seconds", 900),
            "max_attempts": config.get("max_attempts", 3),
            "verify_required": config.get("verify_required", True),
        })

        # 确保目录存在
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def scan_inbox(self) -> list[Path]:
        """
        扫描未处理的 REQ_*.md 文件。

        条件：
        - 文件名匹配 REQ_*.md
        - 不在 processed/ 目录
        - 文件头 Status 不是 processed

        Returns:
            未处理的 REQ 文件路径列表
        """
        pending_reqs = []

        for req_file in self.inbox_dir.glob("REQ_*.md"):
            # 跳过 processed 目录
            if "processed" in str(req_file):
                continue

            # 检查文件头 Status
            try:
                with open(req_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    # 查找 Status 字段
                    status_match = re.search(r'^##\s*Status\s*\n+(\w+)', content, re.MULTILINE)
                    if status_match:
                        status = status_match.group(1).strip().lower()
                        if status == "processed":
                            continue
                    pending_reqs.append(req_file)
            except (IOError, OSError):
                continue

        # 按文件名排序
        return sorted(pending_reqs, key=lambda p: p.name)

    def parse_req(self, req_path: Path) -> dict:
        """
        解析 REQ 文件为结构化数据。

        Args:
            req_path: REQ 文件路径

        Returns:
            解析后的数据字典：
            {
                "req_id": str,
                "title": str,
                "project_requirements": str,
                "config_updates": dict,
                "task_seeds": list[dict]
            }

        Raises:
            ValueError: 解析失败
        """
        with open(req_path, "r", encoding="utf-8") as f:
            content = f.read()

        result = {
            "req_id": "",
            "title": "",
            "project_requirements": "",
            "config_updates": {},
            "task_seeds": [],
        }

        # 解析标题行 (# REQ_XXX: 标题)
        title_match = re.match(r'^#\s*(REQ_\w+):\s*(.+)$', content, re.MULTILINE)
        if title_match:
            result["req_id"] = title_match.group(1)
            result["title"] = title_match.group(2).strip()
        else:
            # 尝试从文件名提取
            result["req_id"] = req_path.stem

        # 解析各个章节
        sections = self._split_sections(content)

        # 项目要求
        if "项目要求" in sections:
            result["project_requirements"] = sections["项目要求"].strip()

        # 运行参数 (YAML 格式)
        if "运行参数" in sections:
            yaml_content = sections["运行参数"]
            # 提取 yaml 代码块
            yaml_match = re.search(r'```ya?ml\s*\n(.*?)\n```', yaml_content, re.DOTALL)
            if yaml_match:
                yaml_text = yaml_match.group(1)
            else:
                yaml_text = yaml_content

            try:
                result["config_updates"] = yaml.safe_load(yaml_text) or {}
            except yaml.YAMLError:
                result["config_updates"] = {}

        # Task Seeds
        if "Task Seeds" in sections:
            result["task_seeds"] = self._parse_task_seeds(sections["Task Seeds"])

        return result

    def _split_sections(self, content: str) -> dict[str, str]:
        """
        将 Markdown 内容按 ## 章节分割。

        Args:
            content: Markdown 内容

        Returns:
            章节名 -> 内容 的字典
        """
        sections = {}
        current_section = None
        current_content = []

        for line in content.split('\n'):
            if line.startswith('## '):
                # 保存上一个章节
                if current_section:
                    sections[current_section] = '\n'.join(current_content)
                # 开始新章节
                current_section = line[3:].strip()
                current_content = []
            elif current_section:
                current_content.append(line)

        # 保存最后一个章节
        if current_section:
            sections[current_section] = '\n'.join(current_content)

        return sections

    def _parse_task_seeds(self, content: str) -> list[dict]:
        """
        解析 Task Seeds 章节。

        格式：
        ### TASK-001: 任务标题
        - goal: 实现 XX 功能
        - acceptance: 通过 YY 测试
        - constraints: 不修改 ZZ 文件
        - verification: pytest tests/
        - scope: src/module/
        - priority: P0
        - depends_on: []

        Args:
            content: Task Seeds 章节内容

        Returns:
            任务种子列表
        """
        tasks = []
        current_task = None

        for line in content.split('\n'):
            line = line.strip()

            # 新任务开始
            if line.startswith('### '):
                if current_task:
                    tasks.append(current_task)
                # 解析任务 ID 和标题
                task_match = re.match(r'###\s*(\S+):\s*(.+)$', line)
                if task_match:
                    current_task = {
                        "id": task_match.group(1),
                        "title": task_match.group(2).strip(),
                        "goal": "",
                        "acceptance": "",
                        "constraints": "",
                        "verification": "",
                        "scope": "",
                        "priority": "P1",
                        "depends_on": [],
                    }
                else:
                    current_task = None

            # 解析任务属性
            elif current_task and line.startswith('- '):
                prop_match = re.match(r'-\s*(\w+):\s*(.*)$', line)
                if prop_match:
                    key = prop_match.group(1)
                    value = prop_match.group(2).strip()

                    # 处理 depends_on 列表
                    if key == "depends_on":
                        if value.startswith('[') and value.endswith(']'):
                            try:
                                value = json.loads(value)
                            except json.JSONDecodeError:
                                value = []
                        elif value:
                            value = [v.strip() for v in value.split(',')]
                        else:
                            value = []

                    if key in current_task:
                        current_task[key] = value

        # 添加最后一个任务
        if current_task:
            tasks.append(current_task)

        return tasks

    def validate_req(self, req: dict) -> tuple[bool, list[str]]:
        """
        校验 REQ 结构。

        必须有：
        - req_id
        - task_seeds (至少一个)
        - 每个 task_seed 必须有 goal 和 acceptance

        Args:
            req: 解析后的 REQ 数据

        Returns:
            (是否有效, 错误列表)
        """
        errors = []

        if not req.get("req_id"):
            errors.append("缺少 req_id")

        task_seeds = req.get("task_seeds", [])
        if not task_seeds:
            errors.append("缺少 task_seeds")
        else:
            for i, seed in enumerate(task_seeds):
                if not seed.get("goal"):
                    errors.append(f"task_seeds[{i}] 缺少 goal")
                if not seed.get("acceptance"):
                    errors.append(f"task_seeds[{i}] 缺少 acceptance")

        return len(errors) == 0, errors

    def generate_unique_task_id(self, base_id: str, existing_ids: set) -> tuple[str, str]:
        """
        生成唯一 task id，冲突时自动改名。

        Args:
            base_id: 原始 ID
            existing_ids: 已存在的 ID 集合

        Returns:
            (新 ID, 映射说明)
        """
        if base_id not in existing_ids:
            return base_id, ""

        # 冲突，添加后缀
        suffix = 1
        while f"{base_id}-{suffix}" in existing_ids:
            suffix += 1

        new_id = f"{base_id}-{suffix}"
        mapping_note = f"原 ID {base_id} 冲突，已改名为 {new_id}"
        return new_id, mapping_note

    def merge_to_claude_md(self, project_requirements: str, claude_md_path: str = "CLAUDE.md") -> str:
        """
        最小 diff 合并到 CLAUDE.md。

        在 "## 项目要求" 章节插入内容。如果章节不存在，在文件末尾添加。

        Args:
            project_requirements: 项目要求内容
            claude_md_path: CLAUDE.md 文件路径

        Returns:
            修改摘要
        """
        if not project_requirements:
            return "无项目要求需要合并"

        claude_md = Path(claude_md_path)
        if not claude_md.exists():
            return "CLAUDE.md 不存在，跳过合并"

        with open(claude_md, "r", encoding="utf-8") as f:
            content = f.read()

        # 查找 "## 项目要求" 章节
        section_pattern = r'(## 项目要求\s*\n)'
        section_match = re.search(section_pattern, content)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        new_content = f"\n<!-- Intake 自动添加 {timestamp} -->\n{project_requirements}\n<!-- End Intake -->\n"

        if section_match:
            # 在章节标题后插入
            insert_pos = section_match.end()
            content = content[:insert_pos] + new_content + content[insert_pos:]
            summary = "在 '## 项目要求' 章节插入内容"
        else:
            # 在文件末尾添加新章节
            content += f"\n\n## 项目要求\n{new_content}"
            summary = "添加 '## 项目要求' 章节"

        with open(claude_md, "w", encoding="utf-8") as f:
            f.write(content)

        return summary

    def merge_config(self, config_updates: dict, task_json_path: str = "Task.json") -> dict:
        """
        合并运行参数到 Task.json config。

        只更新 REQ 中出现的字段，不修改其他字段。

        Args:
            config_updates: 要更新的配置
            task_json_path: Task.json 文件路径

        Returns:
            合并后的 config
        """
        if not config_updates:
            return {}

        with TaskFileLock(task_json_path) as lock:
            data = lock.read()
            current_config = data.get("config", {})

            # 只更新 REQ 中出现的字段
            for key, value in config_updates.items():
                current_config[key] = value

            data["config"] = current_config
            data["last_modified"] = datetime.now(timezone.utc).isoformat()
            lock.write(data)

        return current_config

    def convert_seeds_to_tasks(self, task_seeds: list, existing_ids: set) -> list[dict]:
        """
        转换 Task Seeds 为 Task.json 格式。

        Args:
            task_seeds: 任务种子列表
            existing_ids: 已存在的任务 ID 集合

        Returns:
            Task.json 格式的任务列表
        """
        tasks = []
        id_mappings = []

        for seed in task_seeds:
            # 生成唯一 ID
            new_id, mapping = self.generate_unique_task_id(seed["id"], existing_ids)
            if mapping:
                id_mappings.append(mapping)
            existing_ids.add(new_id)

            # 构建任务描述
            description_parts = [seed.get("title", "")]
            if seed.get("goal"):
                description_parts.append(f"目标: {seed['goal']}")
            if seed.get("acceptance"):
                description_parts.append(f"验收标准: {seed['acceptance']}")
            if seed.get("constraints"):
                description_parts.append(f"约束: {seed['constraints']}")

            description = "\n".join(description_parts)

            # 构建任务
            task = {
                "id": new_id,
                "description": description,
                "status": "pending",
                "last_update": datetime.now(timezone.utc).isoformat(),
                "depends_on": seed.get("depends_on", []),
                "claim": None,
                "result": None,
                "history": [],
                "notes": "",
            }

            # 添加额外元数据
            if seed.get("verification"):
                task["notes"] = f"验证命令: {seed['verification']}"
            if seed.get("scope"):
                task["notes"] += f"\n范围: {seed['scope']}"
            if seed.get("priority"):
                task["notes"] += f"\n优先级: {seed['priority']}"

            # 记录 ID 映射
            if mapping:
                task["notes"] += f"\n{mapping}"

            tasks.append(task)

        return tasks

    def process_req(self, req_path: Path, run_id: str) -> dict:
        """
        处理单个 REQ 文件（主流程）。

        流程：
        1. 解析 REQ
        2. 校验 REQ 结构
        3. 加锁 Task.json
        4. 合并 CLAUDE.md
        5. 合并 config
        6. 转换并追加 tasks
        7. 运行门禁校验
        8. git commit
        9. 移动 REQ 到 processed/
        10. 归档到 runs/

        Args:
            req_path: REQ 文件路径
            run_id: 运行 ID

        Returns:
            处理结果字典
        """
        result = {
            "req_id": "",
            "run_id": run_id,
            "status": "failed",
            "config_updates": {},
            "tasks_added": [],
            "claude_md_patch_summary": "",
            "verify": {"command": "", "exit_code": -1, "evidence": ""},
            "git": {"commit": "", "branch": ""},
            "error": "",
            "needs_human": False,
        }

        # 1. 解析 REQ
        try:
            req = self.parse_req(req_path)
            result["req_id"] = req["req_id"]
        except Exception as e:
            result["error"] = f"解析失败: {e}"
            result["needs_human"] = True
            self.logger.log_intake_fail(run_id, str(req_path), result["error"])
            return result

        # 2. 校验 REQ 结构
        valid, errors = self.validate_req(req)
        if not valid:
            result["error"] = f"校验失败: {', '.join(errors)}"
            result["needs_human"] = True
            self.logger.log_intake_fail(run_id, req["req_id"], result["error"])
            return result

        # 记录开始
        self.logger.log_intake_start(run_id, req["req_id"], str(req_path))

        task_json_path = self.config.get("task_file", "Task.json")
        backup_data = None

        try:
            # 3-7. 在锁内执行所有修改
            with TaskFileLock(task_json_path) as lock:
                data = lock.read()
                backup_data = json.loads(json.dumps(data))  # 深拷贝用于回滚

                # 4. 合并 CLAUDE.md
                claude_md_summary = self.merge_to_claude_md(
                    req.get("project_requirements", ""),
                    self.config.get("claude_md", "CLAUDE.md")
                )
                result["claude_md_patch_summary"] = claude_md_summary

                # 5. 合并 config
                if req.get("config_updates"):
                    current_config = data.get("config", {})
                    for key, value in req["config_updates"].items():
                        current_config[key] = value
                    data["config"] = current_config
                    result["config_updates"] = req["config_updates"]

                # 6. 转换并追加 tasks
                existing_ids = {t["id"] for t in data.get("tasks", [])}
                new_tasks = self.convert_seeds_to_tasks(req["task_seeds"], existing_ids)
                data["tasks"] = data.get("tasks", []) + new_tasks
                result["tasks_added"] = [t["id"] for t in new_tasks]

                # 更新时间戳
                data["last_modified"] = datetime.now(timezone.utc).isoformat()

                # 写入 Task.json
                lock.write(data)

            # 7. 运行门禁校验
            verify_result = self._run_gate_checks()
            result["verify"] = verify_result

            if verify_result["exit_code"] != 0:
                # 回滚 Task.json
                self._rollback_task_json(task_json_path, backup_data)
                result["status"] = "blocked"
                result["error"] = f"门禁校验失败: {verify_result['evidence']}"
                result["needs_human"] = True
                self.logger.log_intake_fail(run_id, req["req_id"], result["error"])
                return result

            # 8. git commit
            git_result = self._git_commit(req["req_id"], result["tasks_added"])
            result["git"] = git_result

            if not git_result.get("commit"):
                result["status"] = "blocked"
                result["error"] = "git commit 失败"
                result["needs_human"] = True
                self.logger.log_intake_fail(run_id, req["req_id"], result["error"])
                return result

            # 9. 移动 REQ 到 processed/
            self.mark_processed(req_path)

            # 10. 成功
            result["status"] = "completed"
            self.logger.log_intake_complete(
                run_id, req["req_id"],
                result["tasks_added"],
                result["config_updates"],
                result["claude_md_patch_summary"],
                result["verify"],
                result["git"]
            )

            return result

        except Exception as e:
            # 回滚
            if backup_data:
                self._rollback_task_json(task_json_path, backup_data)
            result["error"] = str(e)
            result["needs_human"] = True
            self.logger.log_intake_fail(run_id, req.get("req_id", ""), result["error"])
            return result

    def _run_gate_checks(self) -> dict:
        """
        运行门禁校验。

        依次运行：
        1. schema_validator.py
        2. secrets_scanner.py
        3. verify.sh (Windows 上使用 bash)

        Returns:
            验证结果 {command, exit_code, evidence}
        """
        import sys

        checks = [
            ("python scripts/schema_validator.py", "Schema 校验"),
            ("python scripts/secrets_scanner.py", "Secrets 扫描"),
        ]

        # verify.sh 在 Windows 上需要通过 bash 执行
        verify_cmd = self.config.get("verify_command", "scripts/verify.sh")
        if sys.platform == "win32":
            # 尝试使用 bash 执行
            checks.append((f"bash {verify_cmd}", "验证脚本"))
        else:
            checks.append((verify_cmd, "验证脚本"))

        for cmd, name in checks:
            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    timeout=60,
                    cwd=os.getcwd(),
                )
                stdout = result.stdout.decode('utf-8', errors='replace') if result.stdout else ''
                stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ''
                if result.returncode != 0:
                    return {
                        "command": cmd,
                        "exit_code": result.returncode,
                        "evidence": f"{name} 失败: {stderr or stdout}",
                    }
            except subprocess.TimeoutExpired:
                return {
                    "command": cmd,
                    "exit_code": -1,
                    "evidence": f"{name} 超时",
                }
            except FileNotFoundError:
                # 脚本不存在，跳过
                continue

        return {
            "command": "all gate checks",
            "exit_code": 0,
            "evidence": "所有门禁校验通过",
        }

    def _git_commit(self, req_id: str, tasks_added: list) -> dict:
        """
        执行 git commit。

        Args:
            req_id: REQ ID
            tasks_added: 添加的任务 ID 列表

        Returns:
            {commit, branch}
        """
        try:
            # git add
            subprocess.run(
                ["git", "add", "Task.json", "CLAUDE.md"],
                capture_output=True,
                check=True,
            )

            # 获取当前分支
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
            )
            branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

            # git commit
            tasks_str = ", ".join(tasks_added[:5])
            if len(tasks_added) > 5:
                tasks_str += f" (+{len(tasks_added) - 5} more)"

            commit_msg = f"feat(intake): process {req_id}, add {len(tasks_added)} tasks [{tasks_str}]"

            commit_result = subprocess.run(
                ["git", "commit", "-m", commit_msg],
                capture_output=True,
                text=True,
            )

            if commit_result.returncode != 0:
                # 可能没有变更
                if "nothing to commit" in commit_result.stdout:
                    return {"commit": "no-change", "branch": branch}
                return {"commit": "", "branch": branch}

            # 获取 commit hash
            hash_result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
            )
            commit_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else ""

            return {"commit": commit_hash, "branch": branch}

        except Exception:
            return {"commit": "", "branch": ""}

    def _rollback_task_json(self, task_json_path: str, backup_data: dict) -> None:
        """
        回滚 Task.json。

        Args:
            task_json_path: Task.json 路径
            backup_data: 备份数据
        """
        try:
            with TaskFileLock(task_json_path) as lock:
                lock.write(backup_data)
        except Exception:
            pass

    def mark_processed(self, req_path: Path) -> None:
        """
        标记 REQ 为已处理。

        移动到 inbox/processed/ 目录。

        Args:
            req_path: REQ 文件路径
        """
        dest = self.processed_dir / req_path.name
        shutil.move(str(req_path), str(dest))
