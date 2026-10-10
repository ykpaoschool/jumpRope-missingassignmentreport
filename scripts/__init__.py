"""管理员脚本：日常维护用的一次性任务（不参与 Web 服务运行时）。

这些脚本随镜像一起发布（Dockerfile 里 `COPY scripts/`），因为服务器上只有
compose.yaml 与 .env，没有源码——脚本不下去就没法在服务器上执行：

    docker compose exec mailer python3 scripts/clear_send_log.py --all --dry-run

本地开发时在仓库根目录直接跑即可：`python3 scripts/clear_send_log.py ...`。
每个脚本自己把仓库根目录塞进 sys.path，所以两种调用方式都能 `import app`。
"""
