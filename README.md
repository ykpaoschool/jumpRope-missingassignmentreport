# 缺交作业邮件发送工具（Missing Work Mailer）

上传 JumpRope 导出的「缺交作业」Excel，按学生分组生成待发送列表与邮件预览，并通过
Office 365 共享邮箱（应用凭据，非交互式）批量发送给家长。同时支持 **SMTP 渠道**用于快速本地测试。

## 功能

- 上传 `.xlsx` → 按「Student External Id」分组，每个学生一封邮件。
- 邮件正文**中英双语**，以表格列出：课程名称 / 老师 / 评估标题 / 截止日期 / 缺交代码。
- 待发送列表 + 单封邮件预览 + 测试/正式两种发送模式 + 发送结果明细。
- 两种发送渠道：Office 365 (Graph) 与 SMTP（测试用），界面上可切换。
- 家长邮箱缺失的学生会被标红并跳过发送。

## 数据格式

示例见 `data/Missing_Work_Report.xlsx`。第 1 行为表头，A–M 列与示例一致；
**第 14 列（N）为家长邮箱**（示例文件中暂无，实际文件需包含）。若表头中含有
「邮箱 / email / mail / 家长」等关键词，也会自动识别为邮箱列。

## 环境准备

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 然后填写下面的凭据
```

`.env` 需填写：

| 变量 | 说明 |
|---|---|
| `TENANT_ID` | Azure AD 租户 ID |
| `CLIENT_ID` | Azure AD 应用 ID |
| `CLIENT_SECRET` | 应用密钥 |
| `SHARED_MAILBOX` | 共享邮箱 UPN（发信用） |
| `SMTP_HOST` | SMTP 服务器地址（测试渠道） |
| `SMTP_PORT` | SMTP 端口，默认 587 |
| `SMTP_USER` | SMTP 登录账号（可留空） |
| `SMTP_PASSWORD` | SMTP 密码（可留空） |
| `SMTP_FROM` | SMTP 发件人地址 |
| `SMTP_STARTTLS` | 是否启用 STARTTLS，默认 true；465 端口自动走 SSL |
| `SENDER_DISPLAY_NAME` | 落款显示名（可选） |
| `SEND_DELAY_SECONDS` | 每封发送间隔（秒，默认 0.5） |

## SMTP 快速测试（无需 Azure）

只需配置 SMTP 部分，即可在「发送渠道」选择 **SMTP** 快速验证邮件流程：

1. 启动一个本地 SMTP 服务器用于接收测试邮件，例如：

   ```bash
   # 方式一：Python 自带的调试 SMTP 服务器（打印邮件到控制台，端口 1025）
   python3 -m aiosmtpd -n -l localhost:1025

   # 方式二：MailHog / Mailpit（Docker，含网页收件箱）
   docker run -d -p 1025:1025 -p 8025:8025 axllent/mailpit
   ```

2. 在 `.env` 填写：

   ```ini
   SMTP_HOST=localhost
   SMTP_PORT=1025
   SMTP_FROM=no-reply@school.edu
   SMTP_STARTTLS=false
   ```

3. 启动服务，上传 Excel，发送渠道选 **SMTP**，右上角「测试连接」验证，再用测试模式发送。
   - Mailpit 收件箱：http://localhost:8025

> 也可直接填真实邮箱服务商的 SMTP（如 QQ/163/Outlook）进行真实发信测试。

## Azure AD 配置（一次性）

1. 在 [Azure Portal](https://portal.azure.com) → App registrations 注册一个应用。
2. 在「API permissions」添加 Microsoft Graph 的 **`Mail.Send`** 应用权限 → 管理员同意。
3. 在「Certificates & secrets」创建 client secret（记录为 `CLIENT_SECRET`）。
4. 给该应用的服务主体授予共享邮箱「Send As」权限（Exchange Online PowerShell）：

   ```powershell
   Add-MailboxPermission -Identity "shared@domain.com" `
       -User "<应用的服务主体对象ID或名称>" -AccessRights SendAs
   ```

5. 启动后点页面右上角「测试连接」验证凭据与共享邮箱是否可用。

## Docker

本地构建并运行（凭据通过 `--env-file` 注入，不写入镜像）：

```bash
docker build -t missing-work-mailer .
docker run --rm -p 8000:8000 --env-file .env missing-work-mailer
```

打开 http://127.0.0.1:8000 。

镜像也可由 GitHub Actions 自动构建：推送到 `main` 分支或 `v*` 标签即触发，产物推送到
GitHub Container Registry（`ghcr.io/ykpaoschool/jumprope-missingassignmentreport`，`main` 分支同时打 `latest` 标签）。
运行方式：

```bash
docker run --rm -p 8000:8000 --env-file .env ghcr.io/ykpaoschool/jumprope-missingassignmentreport:latest
```

## 启动

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

浏览器打开 http://127.0.0.1:8000 。

## 使用流程

1. 上传 Excel → 查看解析摘要与待发送列表。
2. 点「预览」查看任意学生的邮件内容。
3. 选择发送渠道（Graph / SMTP），先用**测试模式**向测试邮箱发送一封样例确认无误。
4. 切换**正式发送**，勾选学生（或直接全部），确认后发送。

## 注意事项

- 解析结果保存在内存中，重启后需重新上传；适合单机单人使用。
- 正式发送会真实发邮件给家长，请先小批量验证。
- 缺少家长邮箱的学生不会发送，会在列表中标红提示。
