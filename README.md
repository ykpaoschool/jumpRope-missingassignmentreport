# 缺交作业邮件发送工具（Missing Work Mailer）

上传 JumpRope 导出的「缺交作业」Excel，按学生分组生成待发送列表与邮件预览，并通过
Office 365 共享邮箱（应用凭据，非交互式）批量发送给家长。同时支持 **SMTP 渠道**用于快速本地测试。

## 功能

- 上传 `.xlsx` → 按「Student External Id」分组，每个学生一封邮件。
- 文件中有多个邮箱列时可指定用哪一列作为收件地址，列表与统计随之刷新。
- 一个单元格里可以填多个家长邮箱（用 `,` 或 `;` 分隔），该学生的邮件一封发给全部地址。
- 邮件正文**中英双语**，以表格列出：课程名称 / 老师 / 评估标题 / 截止日期 / 缺交代码，
  并附缺交代码释义（M: 缺交作业、X: 未完成作业）与「未按时提交作业处理程序」链接。
- 待发送列表 + 单封邮件预览 + 测试/正式两种发送模式 + 发送结果明细。
- 发送在后台任务中进行：提交后页面立即返回，进度条实时显示「已发送 / 总数 / 失败数」与逐条结果；
  发送期间可以关闭页面，重新打开仍能看到当前进度或最近一次的发送结果。同一时间只允许一个发送任务。
- 两种发送渠道：Office 365 (Graph) 与 SMTP（测试用），界面上可切换。
- 家长邮箱缺失的学生会被标红并跳过发送。
- **发送日志**：每次投递（成功 / 失败）与每一批的开始、结束都记入本地 SQLite
  （`data/mailer.db`），页面第 4 节可按日期与结果翻看。重启服务后记录仍在。

## 数据格式

示例见 `data/Missing_Work_Report.xlsx`。第 1 行为表头，A–M 列与示例一致；
**第 14 列（N）为家长邮箱**。收件地址取哪一列的规则：

1. 表头含「邮箱 / email / mail / 家长」关键词的列，按从左到右的顺序取第一个；
2. 没有这样的列时取第 14 列（N）；
3. 列数不足 14 且表头没有关键词时，取数据中确实出现过邮箱的那一列。

文件中有多个像邮箱的列时，第 1 节会给出**收件邮箱列**选择框：候选列 = 表头含关键词的列，
加上数据中确实出现过邮箱的列。改选后待发送列表与摘要统计立即刷新。只有一列可选时不显示选择框，
改为直接标出当前用的是哪一列；若所选列的邮箱条数明显少于另一列，会在提示里点出来。

单元格里可以放多个地址，用 `,` `;`（全角 `，` `；` 与换行也可）分隔，例如
`father@example.com; mother@example.com`：该学生的邮件**一封**发给全部地址。同一个学生的多行
填了不同的地址时会合并去重后一起发送（并在提示里说明各行不一致），完全重复的地址只发一次。

同一个学生的多行若出现**无法识别的片段**（如 `N/A`、电话号码、`a@x.com 已停用`），
正式发送会被暂停并指出是哪个学生、哪个片段，修正 Excel 后重新上传即可——不会「只挑合法的发」。
上传时第 1 节就会给出这条提示，问题学生的行也会标红。

学生姓名会按以下顺序自动匹配表头，用于邮件正文的「学生姓名 Student Name」：

1. `Student Name`（或 `Student Full Name`、`Student Last First`、`Student Last Name First`）
2. `Student First Name` + `Student Last Name` 两列拼接

两者都不存在时会给出提示，邮件中不显示姓名行。

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
| `SENDER_DISPLAY_NAME` | 邮件落款机构名，默认「包校初中部学术办公室/YK Pao Middle School Academic Affairs Office」 |
| `SENDER_CONTACT_EMAIL` | 邮件落款联系邮箱，默认 `hq-aao@ykpaoschool.cn` |
| `PROCEDURE_URL` | 「查看未按时提交作业处理程序」的跳转地址，留空则该句显示为普通文字 |
| `SEND_DELAY_SECONDS` | 每封发送间隔（秒，默认 0.5）。名单较长（100 封以上）时可适当调小，例如 0.2 |
| `DB_PATH` | 发送日志的 SQLite 库文件路径，默认 `<项目根>/data/mailer.db`；填了就以它为准 |

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

### 本地构建并运行

凭据通过 `--env-file` 注入，不写入镜像；`./data` 挂进容器存放发送日志，容器重建后记录仍在：

```bash
docker build -t missing-work-mailer .
docker run --rm -p 8000:8000 --env-file .env -v "$(pwd)/data:/app/data" missing-work-mailer
```

打开 http://127.0.0.1:8000 。

### 服务器部署（docker compose）

镜像由 GitHub Actions 自动构建：推送到 `main` 分支或 `v*` 标签即触发，产物推送到 GitHub Container
Registry（`ghcr.io/ykpaoschool/jumprope-missingassignmentreport`，`main` 分支同时打 `latest` 标签）。

服务器上只需要 `compose.yaml` 与 `.env` 两个文件，放在同一个目录（项目目录）里：

```bash
mkdir -p data && sudo chown -R 1000:1000 data   # 仅首次，见下方说明
docker compose up -d                            # 首次会自动拉取镜像
```

以后每次升级就是一条命令，不再需要 stop / rm / image rm 那一串：

```bash
docker compose pull && docker compose up -d
```

旧的镜像不会被自动删掉（同一次构建还挂着 `main`、`sha-<commit>` 等标签），留着不占多少事，
而且回滚时本地直接就有。确实要清再手动删，或用下面的 `prune -a` 一次性清掉**所有**没被容器使用的镜像：

```bash
docker image rm <镜像ID>
docker image prune -a -f
```

常用命令：

```bash
docker compose ps          # 查看状态
docker compose logs -f     # 跟踪日志
docker compose restart     # 重启
docker compose down        # 停掉并删除容器，data/ 里的日志不受影响
```

回滚到某次构建（CI 同时会打 `sha-<commit>` 标签）：

```bash
IMAGE_TAG=sha-abc1234 docker compose up -d
```

> 容器对外端口默认 8000，需要改成别的：`HOST_PORT=8001 docker compose up -d`。
>
> `docker compose up -d` 会重建容器，**正在进行的发送批次会被打断**（日志里只有 `job_start`
> 而没有 `job_end`）。请在两次发送之间升级。

容器内以 uid 1000 运行，宿主 `data/` 目录必须对该 uid 可写，否则发送日志写不进去——页面第 4 节
会红字提示库文件路径，发信本身不受影响。该目录若由 `docker compose` 自动创建则属主是 root，
所以上面的 `chown` 不能省。

反向代理（如 Nginx Proxy Manager）保持默认配置即可；若想更保守，可在该 Proxy Host 的
Advanced 里把 `proxy_read_timeout` 调大（例如 300s）。注意 uvicorn 必须保持单 worker。

## 启动

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

浏览器打开 http://127.0.0.1:8000 。

## 使用流程

1. 上传 Excel → 查看解析摘要与待发送列表；文件里有多个邮箱列时，先在「收件邮箱列」里选对列。
   提示里有「家长邮箱含无法识别的地址」时，先修正 Excel 再往下走（否则正式发送会被暂停）。
2. 点「预览」查看任意学生的邮件内容。
3. 选择发送渠道（Graph / SMTP），先用**测试模式**向测试邮箱发送一封样例确认无误
   （测试邮箱也可以填多个，用逗号分隔）。
4. 切换**正式发送**，勾选学生（或直接全部），确认后发送。确认框会写明发几封邮件、
   共涉及几个收件地址：一个学生填了多个家长邮箱时，两者不相等。
5. 发送开始后页面显示进度条与逐条结果；期间可以关闭页面，重新打开会继续显示进度或最近一次结果。
   同一时间只能有一个发送任务，正在发送时再次点击「发送」会提示「已有发送任务进行中」。
6. 到第 4 节「发送日志」核对这次发送；一批发完页面会自动刷新该节，也可以手动「刷新」。

## 发送日志

第 4 节的数据来自 SQLite 单文件（默认 `data/mailer.db`，可用 `DB_PATH` 改），
服务重启、容器重建都不会丢；内存里的发送进度则会丢，两者互补。

- 一次发送会写入三类记录：`job_start`（本批开始，含文件名与收件列）、`send`（每封投递一行，
  成功与失败各一行）、`job_end`（整批结束：成功几封、失败几封，或整批没能开始的原因）。
- 每条记录带发送那一刻的快照：学生、年级、班级、缺交条数、收件人、主题或错误原因、耗时、
  模式（测试 / 正式）与渠道（Graph / SMTP）。`send` 一行对应一封邮件，收件人是该学生的全部
  家长邮箱（多个地址以逗号分隔列出）。
- 页面可按日期（最近 90 天里有记录的日期）和结果（全部 / 仅成功 / 仅失败）筛选，
  右上角显示当日统计。整批在连接阶段就失败时一封都不会发出，这种情况由 `job_end` 记录体现。
- **不记录邮件正文**，所以日志不能单独用来重发；重发要重新上传同一份 Excel，
  日志里的学生 ID 与收件人可用来核对「上次失败的这些人」。
- 数据库不可用时（例如容器内目录权限不对），第 4 节会显示红色提示与库文件路径；
  此时**发信照常进行**，只是这些记录不会留存。
- 日志**不自动清理**，长期使用会持续增长；需要时用下面的管理员脚本裁剪，或直接备份 / 删除该文件。

### 清理发送日志

`scripts/clear_send_log.py` 是随镜像一起发布的管理员脚本，在服务器上的容器内执行：

```bash
docker compose exec mailer python3 scripts/clear_send_log.py --all --dry-run        # 先看会删多少，不动数据
docker compose exec mailer python3 scripts/clear_send_log.py --all                  # 清空，需输入 yes 确认
docker compose exec mailer python3 scripts/clear_send_log.py --before 2026-01-01    # 只删该日期之前（不含当天）的
docker compose exec mailer python3 scripts/clear_send_log.py --day 2026-10-01       # 只删某一天
```

- 删除范围**必须显式指定**（`--all` / `--day` / `--before`），不带范围时只列出当前记录数与用法，一条都不删。
- 除 `--yes` 外，执行前会列出将删除的条数、日期跨度与各事件条数，并要求输入 `yes`（`y` 不算）确认。
- 删完会回收库文件空间（`--no-vacuum` 可关）。发信进行中不要执行，建议在两次发送之间清理。

宿主上装有 `sqlite3` 时也可以直接查库、备份或删除库文件：

```bash
sqlite3 data/mailer.db "select ts, event, student_id, class_name, recipient, ok, error from send_log order by id desc limit 20"
cp data/mailer.db ~/mailer-backup-$(date +%F).db
```

## 注意事项

- 解析结果与发送任务进度都保存在内存中，**重启服务**后需重新上传（刷新页面不会丢：摘要、待发送列表、
  收件邮箱列的选择都会自动恢复，发送日志也会一并保留）；适合单机单人使用。
- 正式发送会真实发邮件给家长，请先小批量验证。
- 缺少家长邮箱的学生不会发送，会在列表中标红提示；邮箱里含无法识别的片段的学生则会
  **拦住整批发送**（列表同样标红，并指出是哪个片段），需要先修正 Excel。
- `data/mailer.db` 内含学生姓名、学号、班级与家长邮箱等个人信息，属内部数据：不要外传，
  不要提交到仓库（`data/` 已在 `.gitignore` 与 `.dockerignore` 中排除）。
