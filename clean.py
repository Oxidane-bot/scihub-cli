#!/usr/bin/env python3
"""
清理脚本 - 删除临时文件和构建产物
"""

import os
import shutil
from pathlib import Path

def main():
    """删除项目中的临时文件和构建产物"""
    # 当前目录
    project_root = Path('.')
    
    # 要删除的目录
    dirs_to_remove = [
        'build',
        'dist',
        'scihub_cli.egg-info',
        '.pytest_cache',
    ]
    
    # 找到所有__pycache__目录
    pycache_dirs = list(project_root.glob('**/__pycache__'))
    
    # 删除指定目录
    for dir_name in dirs_to_remove:
        dir_path = project_root / dir_name
        if dir_path.exists():
            print(f"删除目录: {dir_path}")
            shutil.rmtree(dir_path)
    
    # 删除__pycache__目录
    for pycache in pycache_dirs:
        if pycache.exists():
            print(f"删除目录: {pycache}")
            shutil.rmtree(pycache)
    
    # 删除.pyc文件
    for pyc_file in project_root.glob('**/*.pyc'):
        print(f"删除文件: {pyc_file}")
        os.remove(pyc_file)
    
    print("清理完成!")

if __name__ == "__main__":
    main() 