# Sci-Hub CLI

支持多数据源的学术论文批量下载工具 (Sci-Hub、Unpaywall、arXiv、CORE)

*其他语言版本: [English](README.md), [简体中文](README.zh-CN.md)*

## 功能特点

- **多数据源支持**: 智能路由多个下载源
  - **arXiv**: 预印本优先 (免费,无需 API key)
  - **Unpaywall**: 开放获取论文 (需要邮箱)
  - **Sci-Hub**: 历史论文备选源 (覆盖率高但更慢)
  - **CORE**: 额外的开放获取备选
- **智能年份路由**:
  - 2021年前论文: 先 OA 源，Sci-Hub 兜底
  - 2021年后论文: 仅 OA 源 (跳过 Sci-Hub)
- **并行源查询**: 快源并行查询，慢源作为兜底
- **并行镜像测试**: 快速找到可用的 Sci-Hub 镜像 (通常 <2秒)
- **智能元数据缓存**: 避免跨源重复 API 调用
- **智能回退**: 主要来源失败时自动尝试备用来源
- **灵活输入**: 支持 DOI、arXiv ID，以及 URL（doi.org、直链PDF、PMC文章页、开放获取落地页自动提取PDF等）
- 支持从文本文件批量处理
- 自动镜像选择和测试
- 可自定义输出目录
- 完善的错误处理和重试机制
- PDF验证 (拒绝HTML文件)
- 下载进度报告
- **基于元数据的文件名**: 自动命名为 `[年份] - [标题].pdf` 便于整理

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

2. 使用 lock 文件同步依赖：
   ```bash
   uv sync --frozen
   ```

3. 直接使用Python运行：
   ```bash
   uv run python -m scihub_cli 输入文件.txt
   ```

### 安装故障排除

如果您在安装过程中遇到问题，请尝试以下方法：

1. 确保您安装了Python 3.10+：
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

# 如果在源码仓库中运行
uv run python -m scihub_cli 输入文件.txt
```

其中`输入文件.txt`是包含 DOI / arXiv ID / URL 的文本文件，每行一个。

### 输入文件格式

```
# 以井号开头的行为注释
10.1038/s41586-020-2649-2
https://files.eric.ed.gov/fulltext/EJ1358705.pdf
https://pmc.ncbi.nlm.nih.gov/articles/PMC6505544/
10.1016/s1003-6326(21)65629-7
```

### 可选邮箱（Unpaywall）

如果需要启用 Unpaywall 开放获取查询，请提供邮箱；未设置邮箱时会自动跳过 Unpaywall。

```bash
# 设置邮箱以启用 Unpaywall
scihub-cli papers.txt --email your-email@university.edu
```

邮箱会保存到 `~/.scihub-cli/config.json`，仅用于 Unpaywall 的速率限制，不会跟踪。

### 命令行选项

```
用法: scihub-cli [-h] [-o OUTPUT] [-m MIRROR] [-t TIMEOUT] [-r RETRIES] [-p PARALLEL]
                 [--email EMAIL] [-v] [--version] 输入文件

批量下载学术论文（Sci-Hub、Unpaywall、arXiv、CORE）。

位置参数:
  输入文件              包含DOI或URL的文本文件（每行一个）

选项:
  -h, --help            显示帮助信息并退出
  -o OUTPUT, --output OUTPUT
                        PDF文件的输出目录（默认: ./downloads）
  -m MIRROR, --mirror MIRROR
                        指定要使用的Sci-Hub镜像站点
  -t TIMEOUT, --timeout TIMEOUT
                        请求超时时间（秒）（默认: 15）
 -r RETRIES, --retries RETRIES
                        下载失败时的重试次数（默认: 3）
  -p PARALLEL, --parallel PARALLEL
                        并行下载线程数
  --to-md              下载后将 PDF 转为 Markdown
  --md-output MD_OUTPUT
                        Markdown 输出目录（默认: <pdf_output>/md）
  --md-backend MD_BACKEND
                        转换后端（默认: pymupdf4llm）
  --md-overwrite        覆盖已存在的 Markdown 文件
  --md-warn-only        Markdown 转换失败时仅警告（不影响退出码）
  --trace-html          为失败下载保存 HTML 快照
  --trace-html-dir TRACE_HTML_DIR
                        HTML 快照目录（默认: <output>/trace-html）
  --trace-html-max-chars TRACE_HTML_MAX_CHARS
                        每个 HTML 快照的最大字符数（默认: 2000000）
  --email EMAIL         Unpaywall API 邮箱（会保存到配置文件）
  -v, --verbose         启用详细日志
  --version             显示程序版本号并退出
```

### 使用示例

```bash
# 基本用法
scihub-cli papers.txt

# 下载后自动转 Markdown
# 默认输出目录: <pdf_output_dir>/md
scihub-cli --to-md papers.txt

# 自定义 Markdown 输出目录
scihub-cli --to-md --md-output research/markdown papers.txt

# 开启失败诊断（download-report.json 中包含 source attempts 和 HTML 快照）
scihub-cli --to-md --md-warn-only --trace-html papers.txt

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

该工具采用“多来源查找 + 自动回退”的方式：

1. 读取输入文件（支持 DOI、arXiv ID、URL）
2. （可选）通过 Crossref 获取发表年份，用于智能路由
3. 按路由策略查询多个来源获取 PDF 链接与元数据：
   - 2021 年前：先 OA 源，Sci-Hub 兜底
   - 2021 年后：仅 OA 源（跳过 Sci-Hub）
   - 年份未知：OA 优先，Sci-Hub 兜底
4. 下载 PDF、校验文件有效性（拒绝 HTML）、按元数据生成文件名（如 `[YYYY] - [Title].pdf`）

## 限制

- 并非所有论文都能从这些来源获取到 PDF
- Unpaywall/CORE 只覆盖开放获取（OA）内容
- Sci-Hub 镜像可能变更或临时不可用
- 部分出版商可能会限制自动化下载

## 法律免责声明

此工具仅供教育和研究目的使用。用户负责确保其使用符合适用的法律法规。

## 测试

项目包含全面的测试以确保功能正常工作：

### 运行测试

```bash
# 运行所有单元测试（推荐）
uv run python -m unittest discover -v

# 仅运行某个测试文件
uv run python -m unittest tests/test_metadata_utils.py -v
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
