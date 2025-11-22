# Unpaywall API 邮箱要求 - 执行摘要

## 紧急问题

**当前 Bug**: `scihub-cli` 使用的默认邮箱 `user@example.com` 会被 Unpaywall API **拒绝** (422 错误),导致 Unpaywall 功能完全失效!

## 快速修复

### 临时解决方案

设置环境变量:
```bash
export SCIHUB_CLI_EMAIL="your-real-email@gmail.com"
```

### 永久修复

修改 `scihub_cli/config/settings.py`:
```python
# 从这个:
DEFAULT_EMAIL = 'user@example.com'  # BROKEN!

# 改为这个:
DEFAULT_EMAIL = None  # 要求用户配置

# 或者:
DEFAULT_EMAIL = 'scihub-cli-bot@gmail.com'  # 使用真实邮箱
```

## 核心发现

### 1. 邮箱验证机制

| 邮箱地址 | 结果 | 原因 |
|---------|------|------|
| `test@example.com` | BLOCKED | RFC 2606 保留域名 |
| `user@gmail.com` | OK | 真实域名 |
| `researcher@mit.edu` | OK | 教育机构 |
| `temp@tempmail.com` | OK | 临时邮箱也可以 |

**验证规则**:
- 阻止 `example.com` (RFC 2606 保留域名)
- 接受所有其他真实域名
- **不验证邮箱是否真实存在**
- **不发送验证邮件**

### 2. 邮箱用途

根据 Unpaywall 官方文档:

1. **滥用控制**: 检测到异常使用时联系用户
2. **技术支持**: 服务更新和问题通知
3. **统计研究**: 了解用户群体(聚合数据)

**不用于**:
- 追踪浏览行为
- 关联 IP 地址到个人
- 营销或广告
- 出售给第三方

### 3. 隐私保护

Unpaywall 的隐私承诺:

- IP 地址不关联到邮箱或个人信息
- 浏览器扩展不收集任何个人信息
- 数据保留最多 6 个月
- 可随时请求删除

### 4. 为什么需要邮箱?

**官方原因**:
> "Polite API usage" - 礼貌的 API 使用原则

类似的学术 API (Crossref, OpenAlex) 都采用这种模式:
- 免费访问,但需要身份标识
- 鼓励负责任的使用
- 允许在高流量时联系用户

## 推荐行动

### 对于用户

**立即行动**:
```bash
# 设置真实邮箱
export SCIHUB_CLI_EMAIL="your-email@example.org"

# 验证配置
scihub-cli test.txt -v
```

**不要使用**:
- `test@example.com`
- `user@localhost`
- `admin@test.com`

### 对于开发者

**高优先级修复**:

1. 移除无效的默认邮箱
2. 添加邮箱验证和友好错误提示
3. 更新文档说明邮箱要求
4. 考虑添加交互式配置向导

**代码示例**:
```python
# 验证邮箱函数
def validate_unpaywall_email(email: str) -> bool:
    """验证邮箱是否会被 Unpaywall 接受"""
    if not email:
        return False

    # 检查已知的被阻止域名
    blocked_domains = ['example.com']
    domain = email.split('@')[-1].lower()

    if domain in blocked_domains:
        logger.warning(
            f"Email domain '{domain}' is blocked by Unpaywall. "
            f"Use a real email address (e.g., researcher@university.edu)"
        )
        return False

    return True
```

## 风险评估

| 方案 | 风险 | 说明 |
|-----|------|------|
| 使用真实个人邮箱 | 低 | Unpaywall 隐私保护良好 |
| 使用项目/组织邮箱 | 低 | 推荐方案 |
| 使用共享邮箱 | 中 | 可能触发速率限制 |
| 使用 `example.com` | 高 | 功能完全失效 (422 错误) |

## 替代方案

如果不想提供邮箱:

1. **禁用 Unpaywall**: 仅使用 Sci-Hub
   ```bash
   export SCIHUB_ENABLE_ROUTING=false
   ```

2. **下载数据库快照**: 本地访问,无需 API
   - https://unpaywall.org/products/snapshot

3. **使用浏览器扩展**: 不需要邮箱
   - https://unpaywall.org/products/extension

## 测试结果摘要

**测试方法**: 使用 10 种不同邮箱地址测试 Unpaywall API

**结果**:
- 9/10 邮箱被接受(90%)
- 只有 `example.com` 域名被阻止
- 响应时间: ~1-2 秒
- HTTP 状态: 200 (成功) 或 422 (邮箱被阻止)

**422 错误消息**:
```json
{
  "HTTP_status_code": 422,
  "error": true,
  "message": "Please use your own email address in API calls. See http://unpaywall.org/products/api"
}
```

## 进一步阅读

详细报告: `docs/unpaywall_email_investigation.md`

包含:
- 完整的技术分析
- 隐私政策解读
- 测试结果详情
- 代码实现建议
- 官方文档引用

## 联系方式

**Unpaywall 团队**:
- Email: team@ourresearch.org
- Organization: OurResearch (formerly Impactstory)
- Website: https://unpaywall.org/contact

**问题报告**:
如果邮箱被错误阻止,可以联系 Unpaywall 团队说明情况。
