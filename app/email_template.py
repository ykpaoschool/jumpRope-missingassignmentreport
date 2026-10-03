"""生成中英双语 HTML 邮件正文。"""

from __future__ import annotations

import html as _html

_TH = "border:1px solid #d0d7de; padding:8px; text-align:left; font-size:13px; background:#f2f4f7;"
_TD = "border:1px solid #d0d7de; padding:8px; text-align:left; font-size:13px; color:#333;"
_P = "margin:0 0 14px; font-size:14px; color:#333; line-height:1.7;"

TITLE = "缺交作业通知 Missing Assignments Notification"

# 缺交代码释义（模板固定内容）
CODE_LEGEND = (
    ("M", "缺交作业 Missing Work"),
    ("X", "未完成作业 Incomplete Work"),
)

# 落款与「处理程序」链接的缺省值，正式运行由 config.py 注入
DEFAULT_SENDER_DISPLAY_NAME = "包校初中部学术办公室/YK Pao Middle School Academic Affairs Office"
DEFAULT_SENDER_CONTACT_EMAIL = "hq-aao@ykpaoschool.cn"
DEFAULT_PROCEDURE_URL = "https://shorturl.myykps.cn/ms-pfswt"


def _esc(value) -> str:
    return _html.escape(str(value or ""))


def _norm_grade(grade: str) -> str:
    """'08' -> '8'，非纯数字原样返回。"""
    g = (grade or "").strip()
    return str(int(g)) if g.isdigit() else g


def _procedure_html(procedure_url: str) -> str:
    """「查看处理程序」两句；未配置链接时退化为带下划线的普通文字。"""
    if procedure_url:
        link = f'<a href="{_esc(procedure_url)}" style="color:#1f4e79;">{{}}</a>'
        zh = f"请点击{link.format('此处')}查看未按时提交作业处理程序"
        en = (
            f"Please click {link.format('here')} to view the procedure "
            "for failing to submit work on time."
        )
    else:
        span = '<span style="text-decoration:underline;">{}</span>'
        zh = f"请点击{span.format('此处')}查看未按时提交作业处理程序"
        en = (
            f"Please click {span.format('here')} to view the procedure "
            "for failing to submit work on time."
        )
    return f"{zh}<br/>{en}"


def render_email(
    student: dict,
    sender_display_name: str = DEFAULT_SENDER_DISPLAY_NAME,
    sender_contact_email: str = DEFAULT_SENDER_CONTACT_EMAIL,
    procedure_url: str = DEFAULT_PROCEDURE_URL,
) -> tuple[str, str]:
    """返回 (subject, html)。"""
    sid = _esc(student.get("student_id", ""))
    name = _esc(student.get("student_name", ""))
    grade = _esc(_norm_grade(student.get("grade", "")))
    klass = _esc(student.get("class", ""))

    rows_html = "".join(
        "<tr>"
        f'<td style="{_TD}">{_esc(it.get("course"))}</td>'
        f'<td style="{_TD}">{_esc(it.get("teacher"))}</td>'
        f'<td style="{_TD}">{_esc(it.get("title"))}</td>'
        f'<td style="{_TD}">{_esc(it.get("due_date"))}</td>'
        f'<td style="{_TD}">{_esc(it.get("code"))}</td>'
        "</tr>"
        for it in student.get("items", [])
    )

    # 姓名为空时整行不显示，避免留下空标签
    name_line = f"学生姓名 Student Name：{name}<br/>" if name else ""

    legend_html = "".join(
        f'<div style="margin:0 0 4px 24px;">{_esc(code)}: {_esc(text)}</div>'
        for code, text in CODE_LEGEND
    )

    subject = (
        f"[缺交作业通知] Missing Assignments Notification — "
        f"学生ID {sid} / Grade {grade} / Class {klass}"
    )

    body = f"""\
<div style="font-family:'Segoe UI','Microsoft YaHei',Arial,sans-serif; background:#f6f8fa; padding:24px;">
  <div style="max-width:680px; margin:0 auto; background:#ffffff; border:1px solid #e5e7eb; border-radius:6px; overflow:hidden;">
    <div style="padding:18px 24px; background:#1f4e79; color:#ffffff; font-size:17px; font-weight:bold;">
      {TITLE}
    </div>
    <div style="padding:24px;">
      <p style="{_P}">尊敬的家长 / Dear Parent，</p>
      <p style="{_P}">
        您好！以下是您孩子近期缺交作业记录，烦请查阅并督促孩子及时补交。<br/>
        Please find below the record of missing assignments for your child. Kindly review and
        support your child to submit the work in a timely manner.
      </p>

      <div style="margin:0 0 20px; font-size:14px; color:#333; line-height:1.8;">
        <strong>学生信息 / Student Info</strong><br/>
        {name_line}学号 Student ID：{sid}<br/>
        年级 Grade Level：{grade}
      </div>

      <div style="margin:0 0 12px;">
        <strong style="font-size:14px; color:#333;">作业异常列表 / Missing Assignment List</strong>
        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse; margin-top:8px;">
          <thead>
            <tr>
              <th style="{_TH}">课程名称<br/><span style="font-weight:normal; color:#666;">Section Course Name</span></th>
              <th style="{_TH}">老师<br/><span style="font-weight:normal; color:#666;">Section Teacher Name</span></th>
              <th style="{_TH}">评估标题<br/><span style="font-weight:normal; color:#666;">Assessment Title</span></th>
              <th style="{_TH}">截止日期<br/><span style="font-weight:normal; color:#666;">Assessment Due Date</span></th>
              <th style="{_TH}">缺交代码<br/><span style="font-weight:normal; color:#666;">Missing Work Code</span></th>
            </tr>
          </thead>
          <tbody>
            {rows_html}
          </tbody>
        </table>
      </div>

      <div style="margin:0 0 20px; font-size:13px; color:#333; line-height:1.6;">
        <div style="margin:0 0 4px;">缺交代码 Missing Work Code：</div>
        {legend_html}
      </div>

      <p style="{_P}">{_procedure_html(procedure_url)}</p>

      <p style="{_P}">
        如您有任何疑问，可联系相关学科教师。<br/>
        Should you have any questions, please do not hesitate to contact the relevant subject teacher(s).
      </p>

      <p style="margin:0; font-size:14px; color:#333;">谢谢 / Thank you,</p>
      <p style="margin:0; font-size:14px; color:#333;">{_esc(sender_display_name)}</p>
      <p style="margin:0; font-size:14px; color:#333;">{_esc(sender_contact_email)}</p>
    </div>
  </div>
</div>"""

    return subject, body
