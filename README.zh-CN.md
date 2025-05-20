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

### 方法一：使用pipx（推荐）

[pipx](https://pypa.github.io/pipx/) 允许您在隔离环境中安装和运行Python应用程序。

1. 如果您尚未安装pipx，请先安装：
   ```
   # Windows系统
   pip install pipx
   pipx ensurepath
   
   # macOS系统
   brew install pipx
   pipx ensurepath
   
   # Linux系统
   python3 -m pip install --user pipx
   python3 -m pipx ensurepath
   ```

2. 使用pipx安装scihub-cli：
   ```
   # 从当前目录安装
   pipx install .
   
   # 或从GitHub安装
   pipx install git+https://github.com/Oxidane-bot/scihub-cli.git
   ```

### 方法二：手动安装

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

2. 验证pipx是否正确安装：
   ```
   pipx --version
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
   # 在Windows上
   $env:Path = [System.Environment]::GetEnvironmentVariable("Path","User")
   
   # 在macOS/Linux上
   source ~/.bashrc  # 或 .zshrc, .bash_profile 等
   ```

## 使用方法

### 基本用法

```bash
# 如果使用pipx安装
scihub-cli 输入文件.txt

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

## 许可证

本项目采用MIT许可证 - 详情请参阅LICENSE文件。 