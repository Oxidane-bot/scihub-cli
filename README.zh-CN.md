# Sci-Hub CLI

一个用于从Sci-Hub批量下载学术论文的命令行工具。

*其他语言版本: [English](README.md), [简体中文](README.zh-CN.md)*

## 功能特点

- 支持使用DOI或URL下载论文
- 支持从文本文件批量处理
- 自动选择可用的镜像站点
- 可自定义输出目录
- 完善的错误处理和重试机制
- 下载进度报告
- **基于元数据的文件名：** 尝试使用文章的元数据来命名下载的PDF文件（例如：`[YYYY] - [净化后的标题].pdf`）。这使得文件更具描述性且易于组织。如果无法提取元数据，则会回退到先前的命名方案（基于DOI或输入标识符）。

## 安装方法

[uv](https://docs.astral.sh/uv/) 是一个用Rust编写的极速Python包和项目管理器。

### 安装uv

```
# Windows系统
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS系统
curl -LsSf https://astral.sh/uv/install.sh | sh

# Linux系统
curl -LsSf https://astral.sh/uv/install.sh | sh

# 或通过pip安装
pip install uv
```

### 安装scihub-cli（全局安装）

```
# 从当前目录全局安装
uv tool install .

# 或从GitHub全局安装
uv tool install git+https://github.com/Oxidane-bot/scihub-cli.git

# 临时运行（不安装）
uvx scihub-cli papers.txt
```

**注意**：`uv tool install` 会在您的系统上全局安装该工具，使 `scihub-cli` 命令在终端的任何位置都可用。

### 全局安装 vs 临时使用

- **全局安装**：使用 `uv tool install` 在您的系统上永久安装该工具
- **临时使用**：使用 `uvx scihub-cli` 运行工具而无需安装
- **源码运行**：克隆仓库并使用Python直接运行（适用于开发）

### 手动安装（替代方案）

如果您希望直接从源码运行：

1. 克隆此仓库：
   ```
   git clone https://github.com/Oxidane-bot/scihub-cli.git
   cd scihub-cli
   ```

2. 安装所需依赖：
   ```
   pip install -r requirements.txt
   ```

3. 直接使用Python运行：
   ```
   python -m scihub_cli.scihub_dl 输入文件.txt
   ```

### 安装故障排除

如果您在安装过程中遇到问题，请尝试以下方法：

1. 确保您安装了Python 3.9+：
   ```
   python --version
   ```

2. 验证uv是否正确安装：
   ```
   uv --version
   ```

3. 检查命令是否在您的PATH中：
   ```
   # 在Windows上
   where scihub-cli
   
   # 在macOS/Linux上
   which scihub-cli
   ```

4. 如果遇到"找不到命令"错误，请尝试：
   ```
   # 更新shell环境
   uv tool update-shell
   
   # 在Windows上手动刷新PATH
   $env:Path = [System.Environment]::GetEnvironmentVariable("Path","User")
   
   # 在macOS/Linux上
   source ~/.bashrc  # 或 .zshrc, .bash_profile 等
   ```

## 使用方法

### 基本用法

```bash
# 如果使用uv安装
scihub-cli 输入文件.txt

# 如果临时运行
uvx scihub-cli 输入文件.txt

# 如果直接运行
python -m scihub_cli.scihub_dl 输入文件.txt
```

其中`输入文件.txt`是包含DOI或论文URL的文本文件，每行一个。

### 输入文件格式

```
# 以井号开头的行为注释
10.1038/s41586-020-2649-2
https://www.nature.com/articles/s41586-021-03380-y
10.1016/s1003-6326(21)65629-7
```

### 命令行选项

```
用法: scihub-cli [-h] [-o OUTPUT] [-m MIRROR] [-t TIMEOUT] [-r RETRIES] [-p PARALLEL] [-v] [--version] 输入文件

从Sci-Hub批量下载学术论文。

位置参数:
  输入文件              包含DOI或URL的文本文件（每行一个）

选项:
  -h, --help            显示帮助信息并退出
  -o OUTPUT, --output OUTPUT
                        PDF文件的输出目录（默认: ./downloads）
  -m MIRROR, --mirror MIRROR
                        指定要使用的Sci-Hub镜像站点
  -t TIMEOUT, --timeout TIMEOUT
                        请求超时时间（秒）（默认: 30）
  -r RETRIES, --retries RETRIES
                        下载失败时的重试次数（默认: 3）
  -p PARALLEL, --parallel PARALLEL
                        并行下载数量（默认: 3）
  -v, --verbose         启用详细日志
  --version             显示程序版本号并退出
```

### 使用示例

```bash
# 基本用法
scihub-cli papers.txt

# 指定输出目录
scihub-cli -o research/papers papers.txt

# 使用特定镜像站点
scihub-cli -m https://sci-hub.se papers.txt

# 增加详细度
scihub-cli -v papers.txt

# 临时运行（不安装）
uvx scihub-cli papers.txt
```

## 工作原理

该工具的工作原理是：

1. 读取输入文件并提取DOI/URL
2. 对于每个DOI/URL：
   - 访问Sci-Hub获取论文页面
   - 提取直接下载链接
   - 下载PDF文件
   - 将其保存到输出目录

## 限制

- 并非所有论文都可在Sci-Hub上获取
- Sci-Hub镜像站点可能会变更或不可用
- 该工具依赖于Sci-Hub的网站结构，该结构可能会随时间变化

## 法律免责声明

此工具仅供教育和研究目的使用。用户负责确保其使用符合适用的法律法规。

## 测试

项目包含全面的测试以确保功能正常工作：

### 运行测试

```bash
# 运行所有测试
python tests/test_functionality.py
python tests/test_metadata_utils.py
python tests/test_installation.py

# 使用详细输出运行测试
python -m pytest tests/ -v
```

### 测试结果

测试套件涵盖：
- ✅ **镜像连接性**：测试所有Sci-Hub镜像站点的可访问性
- ✅ **下载功能**：使用真实DOI测试实际论文下载
- ✅ **元数据提取**：测试论文元数据解析和文件名生成
- ✅ **安装**：验证正确的包安装和CLI可用性

### 测试覆盖范围

- **功能测试**：镜像连接性、下载成功、错误处理
- **元数据测试**：标题提取、作者解析、文件名生成
- **安装测试**：包导入、命令可用性、版本检查

## 许可证

本项目采用MIT许可证 - 详情请参阅LICENSE文件。 