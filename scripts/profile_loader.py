#!/usr/bin/env python3
"""
profile_loader.py — 加载并合并 thesis-formatter profile 配置

支持 parent 继承：子 profile 覆盖父 profile 的字段，未覆盖的字段从父继承。
Deep merge 策略：dict 递归合并，list/scalar 直接覆盖。

Usage:
    from profile_loader import load_profile
    config = load_profile("uestc-marxism")  # 返回合并后的完整 dict
"""

import json
import os
import sys
from copy import deepcopy

# Windows console UTF-8 compatibility
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个 dict。override 的值优先。"""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def get_templates_dir() -> str:
    """获取 templates 目录的绝对路径"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(script_dir), "templates")


def load_profile(profile_name: str, templates_dir: str = None) -> dict:
    """
    加载 profile 配置，支持 parent 继承。

    Args:
        profile_name: profile 名称（如 "uestc-marxism"）
        templates_dir: templates 目录路径（默认自动检测）

    Returns:
        合并后的完整配置 dict

    Raises:
        FileNotFoundError: profile 不存在
        ValueError: JSON 解析失败
    """
    if templates_dir is None:
        templates_dir = get_templates_dir()

    profile_dir = os.path.join(templates_dir, profile_name)
    profile_path = os.path.join(profile_dir, "profile.json")

    if not os.path.exists(profile_path):
        raise FileNotFoundError(f"Profile not found: {profile_path}")

    with open(profile_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 处理 parent 继承
    parent_name = config.get("parent")
    if parent_name:
        parent_config = load_profile(parent_name, templates_dir)
        config = _deep_merge(parent_config, config)

    # 注入元信息
    config["_profile_name"] = profile_name
    config["_profile_dir"] = profile_dir

    return config


def get_compile_chain(config: dict) -> list:
    """从 config 提取编译链列表"""
    chain = config.get("compile_chain", [])
    if isinstance(chain, str):
        # 处理 "xelatex → xelatex → xelatex" 格式
        chain = [step.strip() for step in chain.replace("→", ",").split(",")]
    return chain


def get_bibliography_mode(config: dict) -> str:
    """返回 'bibtex' 或 'categorized'"""
    return config.get("bibliography_mode", "bibtex")


def get_citation_style(config: dict) -> str:
    """返回 'cite' 或 'footnote-per-page'"""
    return config.get("citation_style", "cite")


# === CLI 入口 ===

def main():
    """命令行工具：加载并打印 profile"""
    if len(sys.argv) < 2:
        print("Usage: python profile_loader.py <profile_name>")
        print("Available profiles:")
        templates_dir = get_templates_dir()
        if os.path.exists(templates_dir):
            for name in sorted(os.listdir(templates_dir)):
                if os.path.isdir(os.path.join(templates_dir, name)):
                    print(f"  - {name}")
        sys.exit(1)

    profile_name = sys.argv[1]
    try:
        config = load_profile(profile_name)
        print(json.dumps(config, ensure_ascii=False, indent=2))
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
