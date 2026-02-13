#!/usr/bin/env python3
"""
secrets_scanner.py - 敏感信息扫描

扫描范围:
- progress.txt
- runs/*.json
- git diff (未提交的更改)

检测模式:
- API key: sk-[a-zA-Z0-9]{20,}
- Token: token[=:]\\s*['""]?[a-zA-Z0-9_-]{20,}
- 私钥头: -----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----
- AWS key: AKIA[0-9A-Z]{16}
- Generic secret: (password|secret|api_key|apikey)[=:]\\s*['""]?[a-zA-Z0-9_-]{8,}
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# 检测模式
PATTERNS = [
    (r'sk-[a-zA-Z0-9]{20,}', 'OpenAI API Key'),
    (r'AKIA[0-9A-Z]{16}', 'AWS Access Key'),
    (r'-----BEGIN\s+(RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE\s+KEY-----', 'Private Key'),
    (r'(?i)(password|secret|api_key|apikey|token)\s*[=:]\s*[\'"]?[a-zA-Z0-9_\-]{16,}', 'Generic Secret'),
    (r'ghp_[a-zA-Z0-9]{36}', 'GitHub Personal Access Token'),
    (r'gho_[a-zA-Z0-9]{36}', 'GitHub OAuth Token'),
    (r'xox[baprs]-[a-zA-Z0-9\-]{10,}', 'Slack Token'),
]


def scan_file(file_path: str) -> list[dict]:
    """扫描单个文件中的敏感信息。"""
    findings = []

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except (FileNotFoundError, PermissionError):
        return findings

    for pattern, name in PATTERNS:
        for match in re.finditer(pattern, content):
            # 获取行号
            line_num = content[:match.start()].count('\n') + 1
            # 获取匹配内容的前后文（不显示完整 secret）
            matched = match.group()
            masked = matched[:8] + "..." + matched[-4:] if len(matched) > 16 else matched[:4] + "..."

            findings.append({
                "file": file_path,
                "line": line_num,
                "type": name,
                "masked": masked,
            })

    return findings


def scan_git_diff() -> list[dict]:
    """扫描 git diff 中的敏感信息。"""
    findings = []

    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="ignore"
        )
        diff_content = result.stdout or ""

        # 也检查未暂存的更改
        result2 = subprocess.run(
            ["git", "diff"],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="ignore"
        )
        diff_content += result2.stdout or ""

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return findings

    for pattern, name in PATTERNS:
        for match in re.finditer(pattern, diff_content):
            matched = match.group()
            masked = matched[:8] + "..." + matched[-4:] if len(matched) > 16 else matched[:4] + "..."

            findings.append({
                "file": "git diff",
                "line": 0,
                "type": name,
                "masked": masked,
            })

    return findings


def main():
    findings = []

    # 扫描 progress.txt
    if os.path.exists("progress.txt"):
        findings.extend(scan_file("progress.txt"))

    # 扫描 runs/*.json
    runs_dir = Path("runs")
    if runs_dir.exists():
        for f in runs_dir.glob("*.json"):
            findings.extend(scan_file(str(f)))

    # 扫描 git diff
    findings.extend(scan_git_diff())

    if findings:
        print("SECRETS_FOUND")
        for f in findings:
            print(f"  - [{f['type']}] {f['file']}:{f['line']} -> {f['masked']}")
        sys.exit(1)
    else:
        print("SECRETS_OK")
        sys.exit(0)


if __name__ == "__main__":
    main()
