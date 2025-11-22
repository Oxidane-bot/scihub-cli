# Unpaywall API 邮箱要求调查报告

## 执行摘要

Unpaywall API 要求提供邮箱地址作为身份标识和联系方式,主要用于:
1. **滥用控制与联系**: 当检测到异常使用模式时联系用户
2. **用户问责制**: 鼓励负责任的 API 使用
3. **统计和研究**: 了解 API 用户群体(不追踪个人行为)

**关键发现**: Unpaywall 实施**域名黑名单**机制,阻止 RFC 2606 保留域名(如 `example.com`)和常见测试域名,但接受任何真实域名的邮箱(无需验证真实性)。

---

## 1. 官方文档说明

### 1.1 API 认证要求

根据官方文档 (https://unpaywall.org/products/api):

> **Authentication**
> Requests must include your email as a parameter at the end of the URL, like this:
> `api.unpaywall.org/my/request?email=YOUR_EMAIL`

### 1.2 速率限制

- **日请求限制**: 100,000 次/天
- **无需 API Key**: 仅需邮箱地址
- **超额使用**: 建议下载数据库快照进行本地访问

### 1.3 邮箱用途(隐私政策)

根据隐私政策 (https://unpaywall.org/legal/privacy):

**收集的个人信息**:
- 联系信息(姓名和邮箱)
- 组织信息
- API 请求中的邮箱地址

**使用目的**:
1. **与用户沟通**
   - 响应问题或请求
   - 征求反馈
   - 提供技术支持和服务更新通知
   - 告知新功能和工具

2. **促进服务功能**
   - 维护服务安全和运营
   - 追踪使用趋势(聚合数据)

3. **执行权利**
   - 防止禁止或非法活动
   - 执行服务条款
   - 账单和收款

**重要声明**:
> "We do not collect any Personal Information when you use the Browser Extension."
> (浏览器扩展不收集任何个人信息)

> "Our server logs IP addresses of all requests, but we do not link IP addresses to any Personal Information, cookies, usage data, or any other user browsing data."
> (服务器记录 IP 地址,但不关联到个人信息、Cookie 或浏览数据)

---

## 2. 技术实现

### 2.1 邮箱传递方式

**实现方法**: URL 查询参数 (Query Parameter)

```http
GET https://api.unpaywall.org/v2/{doi}?email={email}
```

**HTTP Headers** (来自实际测试):
```http
GET /v2/10.1038/nature12373?email=test@example.com HTTP/1.1
User-Agent: curl/8.15.0
```

邮箱**不通过** HTTP Header 传递,而是作为 URL 参数的一部分。

### 2.2 邮箱验证机制

#### 验证测试结果

| 邮箱地址 | 状态 | 说明 |
|---------|------|------|
| `test@example.com` | **BLOCKED** | RFC 2606 保留域名 |
| `user@localhost` | **OK** | 技术域名,允许 |
| `user@example.org` | **OK** | 非 .com 的 example 域名,允许 |
| `user@example.net` | **OK** | 非 .com 的 example 域名,允许 |
| `test@test.com` | **OK** | 真实注册域名,允许 |
| `john.doe@gmail.com` | **OK** | 真实邮箱服务,允许 |
| `test@gmail.com` | **OK** | Gmail 域名,允许(即使用户名是 "test") |
| `researcher@mit.edu` | **OK** | 教育机构域名,允许 |
| `someone@qq.com` | **OK** | 中国邮箱服务,允许 |
| `user@tempmail.com` | **OK** | 临时邮箱服务,允许 |
| `noreply@unpaywall.org` | **OK** | Unpaywall 自己的域名,允许 |
| (无邮箱参数) | **BLOCKED** | 422 错误 |

#### 域名黑名单规则

**被阻止的域名**:
- `example.com` (RFC 2606 保留域名)
- 可能还包括其他测试/虚假域名

**允许的域名**:
- 所有真实注册的域名
- `localhost` (技术用途)
- `example.org`, `example.net` (非 .com 的 example 域名)
- 临时邮箱服务域名
- 教育机构域名

**错误响应** (被阻止时):
```json
{
  "HTTP_status_code": 422,
  "error": true,
  "message": "Please use your own email address in API calls. See http://unpaywall.org/products/api"
}
```

**错误响应** (缺少邮箱时):
```json
{
  "HTTP_status_code": 422,
  "error": true,
  "message": "Email address required in API call, see http://unpaywall.org/products/api"
}
```

### 2.3 邮箱验证深度

**验证内容**:
1. 邮箱格式必须有效(包含 @ 和域名)
2. 域名不能在黑名单中
3. **不验证**邮箱是否真实存在
4. **不验证**域名的 MX 记录
5. **不发送**验证邮件

**结论**: Unpaywall 使用**最小验证**策略,仅阻止明显的测试域名,不验证邮箱的真实性。

---

## 3. 隐私和安全

### 3.1 隐私政策要点

**数据收集**:
- API 调用中的邮箱地址
- IP 地址(仅用于技术目的,如负载均衡和 bug 修复)
- 请求的 DOI(用于查找文章信息)

**不收集**:
- 姓名(除非主动提供)
- 浏览历史
- Cookie 或追踪数据(API 层面)
- 浏览器扩展用户的个人信息

**数据使用**:
- IP 地址不关联到个人信息
- 邮箱仅用于联系和服务改进
- 可能编译聚合数据报告(不包含个人识别信息)

### 3.2 第三方共享

**共享情况**:
- 与第三方服务提供商共享(如邮件服务器提供商)
- 仅在必要时用于促进服务
- 第三方仅按指示使用,遵循隐私政策

**不共享**:
- 不出售、交易或出租个人信息
- 未经同意不与第三方共享

**例外情况**:
1. 遵守法院命令、法律或监管要求
2. 执行服务条款和协议
3. 保护 Impactstory、客户或他人的权利、财产或安全

### 3.3 数据保留政策

**保留期限**:
- 使用服务期间保留
- 停止使用后最多保留 **6 个月**
- 可请求提前删除

**删除权利**:
- 可随时请求个人数据副本
- 可请求更正或删除个人数据
- 可反对或限制数据处理

**联系方式**: team@ourresearch.org

### 3.4 安全措施

**技术保护**:
- 加密
- 防火墙
- SSL (Secure Socket Layer) 技术

**风险声明**:
> "However, these measures do not guarantee that your information will not be accessed, disclosed, altered or destroyed by breach of such firewalls and secure server software. By using our Service, you acknowledge that you understand and agree to assume these risks."

---

## 4. 实际测试结果

### 4.1 测试方法

使用 curl 命令测试不同邮箱地址:

```bash
curl -s "https://api.unpaywall.org/v2/10.1038/nature12373?email={email}"
```

### 4.2 成功的请求示例

**请求**:
```bash
curl "https://api.unpaywall.org/v2/10.1038/nature12373?email=researcher@university.edu"
```

**响应** (200 OK):
```json
{
  "doi": "10.1038/nature12373",
  "title": "Nanometre-scale thermometry in a living cell",
  "is_oa": true,
  "oa_status": "bronze",
  "year": 2013,
  "best_oa_location": {
    "url": "https://www.nature.com/articles/nature12373.pdf",
    "url_for_pdf": "https://www.nature.com/articles/nature12373.pdf",
    "host_type": "publisher",
    "version": "publishedVersion"
  }
}
```

### 4.3 被阻止的请求示例

**请求**:
```bash
curl "https://api.unpaywall.org/v2/10.1038/nature12373?email=test@example.com"
```

**响应** (422 Unprocessable Entity):
```json
{
  "HTTP_status_code": 422,
  "error": true,
  "message": "Please use your own email address in API calls. See http://unpaywall.org/products/api"
}
```

### 4.4 422 错误的原因

**HTTP 422 (Unprocessable Entity)** 表示:
- 请求格式正确(语法有效)
- 但语义上无法处理(邮箱域名在黑名单中)

这是 Unpaywall 的**主动策略**,阻止使用测试邮箱的自动化脚本。

---

## 5. 替代方案

### 5.1 其他获取方式

**无需邮箱的替代方案**:
1. **数据库快照** (https://unpaywall.org/products/snapshot)
   - 完整数据库下载
   - 本地访问,无需 API 调用
   - 更新频率: 定期更新

2. **浏览器扩展** (https://unpaywall.org/products/extension)
   - Chrome/Firefox 插件
   - **不收集个人信息**
   - **不需要邮箱**
   - 仅发送 DOI 到服务器

3. **Data Feed** (https://unpaywall.org/products/data-feed)
   - 企业级订阅服务
   - 需要注册和付费
   - 提供唯一 API Key

### 5.2 使用匿名/临时邮箱

**测试结果**: 临时邮箱服务(如 `tempmail.com`)被允许

**建议**:
- 使用真实但非个人的邮箱(如 `research-bot@gmail.com`)
- 使用组织邮箱(如 `library@university.edu`)
- 避免使用 `example.com` 等保留域名

### 5.3 其他认证方式

**当前**: 仅支持邮箱参数

**未来可能**:
- API Key (目前仅 Data Feed 订阅提供)
- OAuth 认证(未实施)

---

## 6. 为什么要求邮箱?

### 6.1 官方原因

根据文档和社区讨论:

1. **"Polite" API 使用** (礼貌的 API 使用)
   - 类似于 Crossref、OpenAlex 等学术 API 的做法
   - 允许服务提供商在高流量时联系用户
   - 鼓励负责任的使用

2. **滥用检测和预防**
   - 检测到异常使用模式时可以联系
   - 防止恶意爬虫和 DDoS 攻击
   - 提供问责机制

3. **用户研究和改进**
   - 了解 API 用户群体(如学术机构、图书馆等)
   - 收集反馈改进服务
   - 统计使用趋势

### 6.2 与其他学术 API 的比较

**OpenAlex API**:
- 同样要求邮箱
- 提供 "polite pool" (礼貌池)机制
- 提供邮箱的用户获得更高速率限制

**Crossref API**:
- 强烈推荐但不强制要求邮箱
- User-Agent 中包含邮箱获得更好性能

**Unpaywall**:
- **强制要求**邮箱
- 无邮箱返回 422 错误
- 无 "polite pool" 差异化待遇

### 6.3 设计哲学

Unpaywall 的方法平衡了:
- **开放性**: 免费、无需注册、无 API Key
- **问责制**: 要求邮箱标识
- **隐私保护**: 不追踪浏览行为,不关联 IP 到个人信息
- **滥用控制**: 阻止明显的测试邮箱,鼓励真实联系方式

---

## 7. 对 scihub-cli 项目的建议

### 7.1 当前实现回顾

**当前代码** (`scihub_cli/sources/unpaywall_source.py`):
```python
def __init__(self, email: str, timeout: int = 30):
    self.email = email
    self.session.headers.update({
        'User-Agent': f'scihub-cli/1.0 (mailto:{email})'
    })
```

**当前配置** (`scihub_cli/config/settings.py`):
```python
DEFAULT_EMAIL = 'user@example.com'
```

**问题**: `user@example.com` 会导致 **422 错误**!

### 7.2 推荐的修改

#### 选项 1: 要求用户配置邮箱(推荐)

```python
# settings.py
DEFAULT_EMAIL = None  # 不提供默认值

# client.py 或 scihub_dl_refactored.py
def validate_email(email):
    """验证邮箱格式并警告保留域名"""
    if not email:
        raise ValueError("Email is required for Unpaywall API. Set SCIHUB_CLI_EMAIL environment variable.")

    # 检查是否是已知的被阻止域名
    blocked_domains = ['example.com']
    domain = email.split('@')[-1].lower()
    if domain in blocked_domains:
        raise ValueError(f"Email domain '{domain}' is blocked by Unpaywall. Use a real email address.")

    return email
```

#### 选项 2: 提供安全的默认邮箱

```python
# settings.py
DEFAULT_EMAIL = 'scihub-cli-user@gmail.com'  # 或项目维护者的邮箱
```

**优点**: 开箱即用
**缺点**: 所有用户共享同一邮箱,可能触发速率限制

#### 选项 3: 在首次运行时提示用户

```python
# 首次运行时交互式配置
if not settings.email:
    print("Unpaywall API requires an email address for usage tracking.")
    print("This is used to contact you if there are issues with your usage.")
    print("Privacy: Your email is not linked to your browsing data.")
    email = input("Enter your email address: ")
    # 保存到配置文件
```

### 7.3 文档更新建议

更新 `CLAUDE.md` 和 `README.md`:

```markdown
### Environment Variables

Configure via environment variables:
```bash
# REQUIRED: Real email address for Unpaywall API
# DO NOT use test@example.com or other RFC 2606 reserved domains
export SCIHUB_CLI_EMAIL="your-email@university.edu"

# Optional settings
export SCIHUB_YEAR_THRESHOLD=2021
export SCIHUB_ENABLE_ROUTING=true
```

**Important**:
- Use a real email address (e.g., `researcher@university.edu`)
- Unpaywall blocks RFC 2606 reserved domains (`example.com`, etc.)
- Your email is used for abuse prevention only
- No personal data is tracked or shared
```

### 7.4 错误处理改进

```python
# unpaywall_source.py
def get_pdf_url(self, doi: str) -> Optional[str]:
    try:
        response = self.session.get(url, params=params, timeout=self.timeout)

        if response.status_code == 422:
            error_data = response.json()
            if "email" in error_data.get("message", "").lower():
                logger.error(
                    f"[Unpaywall] Invalid email address rejected: {self.email}. "
                    f"Use a real email address. Avoid test@example.com and similar domains."
                )
                return None

        # ... 其他处理
```

---

## 8. 结论

### 8.1 核心发现

1. **邮箱是强制要求的**,缺少邮箱会导致 422 错误
2. **邮箱验证采用黑名单机制**,阻止 `example.com` 等保留域名
3. **不验证邮箱真实性**,任何真实域名的邮箱都会被接受
4. **邮箱主要用于联系和滥用控制**,不追踪个人浏览行为
5. **隐私保护良好**,IP 地址不关联到个人信息

### 8.2 最佳实践

**对于 API 用户**:
- 使用真实但非个人的邮箱(如项目邮箱、组织邮箱)
- 避免使用 `test@example.com`、`user@localhost` 等明显的测试邮箱
- 遵守 100,000 次/天的速率限制
- 大规模使用时下载数据库快照

**对于 scihub-cli 项目**:
- **立即修复**: 移除 `user@example.com` 默认值
- **要求配置**: 通过环境变量或交互式提示获取用户邮箱
- **提供指导**: 在文档中明确说明邮箱要求和隐私政策
- **错误处理**: 提供清晰的 422 错误提示

### 8.3 风险评估

**使用真实邮箱的风险**: **低**
- Unpaywall 隐私政策明确不追踪个人行为
- 邮箱不与 IP 地址或浏览数据关联
- 仅在异常使用时才会联系
- 可随时请求删除数据

**使用共享邮箱的风险**: **中等**
- 可能触发速率限制(100,000 次/天)
- 多用户共享可能导致服务中断
- Unpaywall 可能将其标记为机器人

**使用假邮箱的风险**: **高**
- 422 错误导致功能完全失效
- 违反 Unpaywall 的使用条款
- 可能导致 IP 封禁

### 8.4 推荐方案

**对于 scihub-cli**:

1. **短期修复** (紧急):
   ```python
   DEFAULT_EMAIL = 'scihub-cli@ourresearch.org'  # 联系 Unpaywall 团队申请项目邮箱
   ```

2. **长期方案** (推荐):
   - 要求用户通过环境变量提供邮箱
   - 在首次运行时提示配置
   - 提供清晰的文档和隐私说明
   - 考虑提供 "匿名模式"(仅使用 Sci-Hub,跳过 Unpaywall)

3. **文档更新**:
   - 说明邮箱要求的原因
   - 引用 Unpaywall 隐私政策
   - 提供配置示例

---

## 9. 参考资料

### 官方文档
- Unpaywall REST API: https://unpaywall.org/products/api
- Privacy Policy: https://unpaywall.org/legal/privacy
- Data Format Guide: https://unpaywall.org/data-format
- FAQ: https://unpaywall.org/faq

### 技术资源
- unpywall 文档: https://unpywall.readthedocs.io/
- Unpaywall GitHub: https://github.com/ourresearch/oadoi
- Support Portal: https://support.unpaywall.org/

### 联系方式
- Email: team@ourresearch.org
- Organization: Impactstory, Inc. (OurResearch)
- Address: 500 Westover Dr #8234, Sanford NC, 27330-8941
- Phone: 778-848-4724

---

**报告生成时间**: 2025-11-22
**调查方法**: 官方文档分析 + 实际 API 测试 + 隐私政策审查
**测试工具**: curl, Python, Bash scripts
