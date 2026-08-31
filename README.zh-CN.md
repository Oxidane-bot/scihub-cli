# Sci-Hub CLI

支持多数据源的学术论文批量下载工具 (OpenAlex、Europe PMC、OpenAIRE、Sci-Hub、Unpaywall、arXiv、CORE)

*其他语言版本: [English](README.md), [简体中文](README.zh-CN.md)*

## 功能特点

- **多数据源支持**: 智能路由多个下载源
  - **OpenAlex**: 开放获取元数据与全文链接发现（无需邮箱）
  - **Europe PMC**: 生物医学 OA 全文链接（无需邮箱）
  - **OpenAIRE**: 在更快的 OA 来源之后顺序查询的仓储链接备选源（无需邮箱）
  - **arXiv**: 预印本优先 (免费,无需 API key)
  - **Unpaywall**: 开放获取论文 (需要邮箱)
  - **Sci-Hub**: 可选的历史论文备选源（需要用户提供并通过检查的镜像）
  - **CORE**: 额外的开放获取备选（默认关闭，可用 `--enable-core` 开启）
- **智能年份路由**:
  - 2021年前论文: 先 OA 源，再尝试可用的 Sci-Hub 镜像
  - 2021年后论文: 仅 OA 源 (跳过 Sci-Hub)
- **并行源查询**: 快源并行查询，慢源作为兜底
- **论文级镜像检查**: 针对具体论文页面和 PDF 链接验证用户提供的镜像
- **智能元数据缓存**: 避免跨源重复 API 调用
- **智能回退**: 主要来源失败时自动尝试备用来源
- **灵活输入**: 支持 DOI、arXiv ID，以及 URL（doi.org、直链PDF、PMC文章页、开放获取落地页自动提取PDF等）
- 支持从文本文件批量处理
- 使用前验证显式指定的镜像
- 可自定义输出目录
- 完善的错误处理和重试机制
- PDF验证 (拒绝HTML文件)
- 下载进度报告
- **基于元数据的文件名**: 自动命名为 `[年份] - [标题].pdf` 便于整理

## 最近更新

### v0.5.4

- 保留跨来源的唯一候选 URL，主候选失败时进行有界回退
- 对等价的 arXiv、PMC 和 DOI 输入安全去重，并让 arXiv 直链 PDF 直接进入下载路由
- 增加可安全恢复的进程预留锁，支持陈旧锁和已退出进程的恢复
- 尊重来源返回的 `Retry-After` 并增加按主机限流；改进 OpenAIRE 解析，并为 OSTI 下载增加有界
  deadline 宽限
- 根据开放获取批量基准将默认下载并发调优为 `4`；需要时仍可通过 `--parallel` 显式提高

### v0.5.3

- 修复 wheel 隔离安装后的真实网络 E2E，并新增 Python 3.10-3.14 CI
- PyPI 发布前强制执行测试、lint、构建和已安装 wheel 烟测
- 修复 CLI/包版本漂移、输入文件不可读时的退出码和 arXiv 重试分类
- 避免同名或并发下载互相覆盖已有文件
- 移除过时的默认 Sci-Hub 镜像；镜像必须由用户提供并通过论文级检查
- 增加流式下载大小限制，并收紧本地配置和日志目录权限
- 可选的 `r.jina.ai` 阅读器回退不再转发落地页 query 参数

### v0.5.2

- 新增 GitHub Copilot、OpenClaw 和 OpenCode 的用户级 Skill 安装
- Gemini CLI 继续保留在默认安装目标中

### v0.5.1

- 新增 `scihub-cli skill install`，可将内置 Skill 安装到 Codex、Claude Code 和 Gemini CLI
- 将 OpenAIRE 接入为更快 OA 来源之后的顺序备选源

### v0.4.1

- 提升 `--to-md` 稳定性：Markdown 转换在内部串行执行，降低并行下载下随机转换崩溃的概率
- 增加旧版 `uv tool` 环境的升级说明，避免工具缓存导致仍运行旧转换逻辑

### v0.5.0

- `--academic-only` 改为默认开启：下载前过滤明显非学术链接
- 增强 URL 规范化与去重：自动清理追踪参数、fragment、`www` 变体等噪声
- 集成 OpenAlex 来源并优化 OA 优先路由
- 新增 Europe PMC OA 来源（生物医学 OA 覆盖，无需邮箱）
- 优化 fast-fail：对挑战页/付费墙页更快失败，减少无效重试
- 增强 PMC 回退：当 PMC PDF 链接返回 HTML 时，自动尝试 EuropePMC 渲染端点
- 默认并发曾提升为 `16`，在大批量下载下取得更好的速度/成功率平衡

### 当前默认值

- 默认下载并发为 `4`，在受速率限制的开放获取来源上更稳定。若输入规模和来源允许
  更高并发，可通过 `--parallel` 显式调高。

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

### 安装scihub-cli（推荐）

```
# 从 PyPI 安装
pip install scihub-cli

# 或使用 uv 全局安装
uv tool install scihub-cli

# 临时运行（不安装）
uvx scihub-cli papers.txt
```

### 开发/源码安装

```
# 从当前目录安装（适合开发）
uv tool install .

# 或从 GitHub 安装未发布版本
uv tool install git+https://github.com/Oxidane-bot/scihub-cli.git
```

**注意**：`pip install scihub-cli` 和 `uv tool install scihub-cli` 使用已发布版本；`uv tool install .` 更适合本地开发。

### 安装内置的 AI 编程 Agent Skill

安装 CLI 后，以下命令会把内置 Skill 安装到所有支持的用户级 Agent：

```
scihub-cli skill install
```

默认目标为 Codex、Claude Code、Gemini CLI、GitHub Copilot、OpenClaw 和 OpenCode。可以指定目标，或覆盖已安装的 Skill：

```
scihub-cli skill install --target copilot,openclaw,opencode
scihub-cli skill install --target gemini-cli --force
```

Skill 会指导 Agent 准备批量输入、调用下载器和核验结果；它不配置 MCP 服务。Cursor 的公开定制规范目前是 Rules/Commands，而非用户级 `SKILL.md` 目录，因此不伪装成原生 Skill 目标。

### 全局安装 vs 临时使用

- **全局安装**：使用 `pip install scihub-cli` 或 `uv tool install scihub-cli`
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

5. 如果是通过 PyPI 安装，升级时可使用：
   ```
   pip install --upgrade scihub-cli
   ```

6. 如果升级后 `--to-md` 表现仍像旧版本，请强制刷新本地工具环境：
   ```
   # 已发布版本
   uv tool install --force --reinstall --refresh scihub-cli

   # 本地开发副本
   uv tool install --force --reinstall --refresh .
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

在 POSIX 系统上，配置目录默认权限为 `0700`，配置文件为 `0600`。单个
下载文件默认限制为 100 MiB；可通过设置正整数环境变量
`SCIHUB_MAX_FILE_SIZE`（字节）调整上限。

项目不再内置 Sci-Hub 镜像：镜像域名变化频繁，首页返回 HTTP 200 不能证明
它能提供论文。使用 `--mirror https://...` 指定镜像后，CLI 会检查具体 DOI
页面并要求存在明确的 PDF/下载链接；必要时可用 `SCIHUB_MIRROR_PROBE_DOI`
指定用于健康检查的 DOI。

### 命令行选项

```
用法: scihub-cli [-h] [-o OUTPUT] [-m MIRROR] [-t TIMEOUT] [-r RETRIES] [-p PARALLEL]
                 [--enable-core] [--fast-fail] [--no-fast-fail] [--academic-only]
                 [--no-academic-only]
                 [--email EMAIL] [-v] [--version] 输入文件

从多个开放获取来源批量下载学术论文，并可选使用 Sci-Hub 备选源。

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
                        并行下载线程数（默认: 4）
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
  --enable-core         启用 CORE 来源查询（默认关闭，避免限流导致变慢）
  --fast-fail           永久失败时跳过 bypass 和 HTML 恢复（默认开启）
  --no-fast-fail        允许较慢的 bypass 和 HTML 恢复
  --download-deadline DOWNLOAD_DEADLINE
                        单次下载的硬截止时间（秒）
  --academic-only       下载前过滤明显非学术 URL（默认开启）
  --no-academic-only    关闭学术过滤，处理所有输入 URL
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

# 默认已启用 fast-fail（默认并发为 4）
scihub-cli -r 1 -t 8 papers.txt

# 默认已开启学术过滤（只处理学术输入）
scihub-cli papers.txt

# 关闭学术过滤（处理所有 URL）
scihub-cli --no-academic-only papers.txt

# 若希望更激进的恢复策略，可关闭 fast-fail
scihub-cli --no-fast-fail papers.txt

# 需要时再启用 CORE（默认关闭）
scihub-cli --enable-core papers.txt

# 指定输出目录
scihub-cli -o research/papers papers.txt

# 使用用户提供的镜像站点（使用前会进行论文级检查）
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
   - 2021 年前：先快速 OA 来源，再 OpenAIRE，最后尝试可用的 Sci-Hub 镜像
   - 2021 年后：先快速 OA 来源，再 OpenAIRE（跳过 Sci-Hub）
   - 年份未知：先快速 OA 来源，再 OpenAIRE，最后尝试可用的 Sci-Hub 镜像
4. 下载 PDF、校验文件有效性（拒绝 HTML）、按元数据生成文件名（如 `[YYYY] - [Title].pdf`）

## 限制

- 并非所有论文都能从这些来源获取到 PDF
- Unpaywall/CORE 只覆盖开放获取（OA）内容
- Sci-Hub 镜像经常变化，项目当前不提供默认镜像
- 部分出版商可能会限制自动化下载
- `r.jina.ai` 回退不会携带 query 参数，因此依赖 query 参数的页面可能无法恢复
- 100 MiB 的单文件上限用于防止意外的无界下载；大文件可通过 `SCIHUB_MAX_FILE_SIZE` 调整

## 法律免责声明

此工具仅供教育和研究目的使用。用户负责确保其使用符合适用的法律法规。

## 与 AI Agent 配合使用（MCP）

[paper-download-mcp](https://github.com/Oxidane-bot/paper-download-mcp) 是一个独立的 MCP 服务，和本项目共用核心逻辑，并已发布到 PyPI。它可以作为 agent 调用的论文下载工具。先安装 `uv`（可用 `uvx --version` 验证），然后：

### Claude Code

```bash
claude mcp add --transport stdio --scope project --env PAPER_DOWNLOAD_EMAIL=your-email@university.edu paper-download -- uvx paper-download-mcp
```

### Claude Desktop

编辑 MCP 配置（macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`，Windows：`%APPDATA%\Claude\claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "paper-download": {
      "command": "uvx",
      "args": ["paper-download-mcp"],
      "env": {
        "PAPER_DOWNLOAD_EMAIL": "your-email@university.edu"
      }
    }
  }
}
```

### Codex

```bash
codex mcp add paper-download --env PAPER_DOWNLOAD_EMAIL=your-email@university.edu -- uvx paper-download-mcp
```

## Longrun 迭代流程

关于由代理连续执行“运行、检查、修改、继续下一轮”，并在最后保留最佳版本代码与总结报告的长跑流程，请参考：

- `docs/longrun_benchmark.md`

## 测试

项目包含全面的测试以确保功能正常工作：

### 运行测试

```bash
# 运行默认的离线/单元测试（推荐）
uv run pytest -q

# 运行需联网的集成测试（显式开启）
SCIHUB_CLI_RUN_NETWORK_TESTS=1 uv run pytest -q -m integration

# 构建并安装 wheel 后运行安装级 E2E（显式开启）
SCIHUB_CLI_RUN_INTEGRATION=1 uv run pytest -q -m e2e
```

### 测试结果

测试套件涵盖：
- ✅ **镜像验证**：确保不会把 HTTP 200 首页误判为论文/PDF 可用
- ✅ **配置安全**：检查凭据和日志的私有权限
- ✅ **下载功能**：网络测试显式开启后才检查真实提供方
- ✅ **元数据提取**：测试论文元数据解析和文件名生成
- ✅ **安装**：验证正确的包安装和CLI可用性

### 测试覆盖范围

- **功能测试**：论文级镜像验证、下载大小边界、错误处理
- **元数据测试**：标题提取、作者解析、文件名生成
- **安装测试**：包导入、命令可用性、版本检查

项目不在 README 中承诺固定成功率。提供方状态、网络、论文是否开放获取、
限流和可选镜像都会影响结果；请在实际环境中运行上面的集成/E2E 命令，并
查看失败报告。

## 许可证

本项目采用MIT许可证 - 详情请参阅LICENSE文件。 
