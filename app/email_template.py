"""生成中英双语 HTML 邮件正文。"""

from __future__ import annotations

import html as _html

_TH = "border:1px solid #d0d7de; padding:8px; text-align:left; font-size:13px; background:#f2f4f7;"
_TD = "border:1px solid #d0d7de; padding:8px; text-align:left; font-size:13px; color:#333;"
_P = "margin:0 0 14px; font-size:14px; color:#333; line-height:1.7;"

TITLE = "缺交作业通知 Missing Assignments Notification"

# 缺交代码释义（模板固定内容）。M 行不再发提醒邮件，所以只解释 X
CODE_LEGEND = (
    ("X", "Missing (did not submit but should have) 未提交（应当提交但未上交）"),
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
      <p style="{_P}">亲爱的家长与同学 / Dear Parent and Student,</p>
      <p style="{_P}">
        您好！以下是学生近期缺交作业记录，请同学及时补交作业，也请家长协助督促，共同帮助同学养成按时完成作业的良好学习习惯。感谢配合！<br/>
        Please see below the record of the student’s missing assignments. We encourage the student to
        complete and submit the outstanding work as soon as possible. Parents are also kindly asked to
        support and encourage their child in developing the habit of completing assignments on time.
        Many thanks!
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
        请注意：尽管形成性评价的结果不会直接计入学生的学业表现等级，但它持续追踪学习情况，并借助清晰、有指导性的教师反馈帮学生找到提升方向。我们要求学生认真完成所有形成性评价任务，这类练习也将为总结性评价取得良好表现打下基础。<br/>
        如您有任何疑问，请联系相关学科教师。<br/>
        Please note that although formative evidence doesn’t contribute directly to the students’
        achievement level, it tracks ongoing learning and identifies areas for growth through clear,
        actionable feedback from teachers. We require students to complete all formative tasks, as this
        practice builds the foundation needed to succeed in summative assessments.<br/>
        Should you have any questions, please do not hesitate to contact the relevant subject teacher(s).
      </p>

      <p style="margin:0; font-size:14px; color:#333;">谢谢 / Thank you,</p>
      <p style="margin:0; font-size:14px; color:#333;">{_esc(sender_display_name)}</p>
      <p style="margin:0; font-size:14px; color:#333;">{_esc(sender_contact_email)}</p>
    </div>
  </div>
</div>"""

    return subject, body
