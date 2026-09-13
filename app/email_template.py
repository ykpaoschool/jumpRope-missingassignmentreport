"""生成中英双语 HTML 邮件正文。"""

from __future__ import annotations

import html as _html

_TH = "border:1px solid #d0d7de; padding:8px; text-align:left; font-size:13px; background:#f2f4f7;"
_TD = "border:1px solid #d0d7de; padding:8px; text-align:left; font-size:13px; color:#333;"


def _esc(value) -> str:
    return _html.escape(str(value or ""))


def _norm_grade(grade: str) -> str:
    """'08' -> '8'，非纯数字原样返回。"""
    g = (grade or "").strip()
    return str(int(g)) if g.isdigit() else g


def render_email(student: dict, sender_display_name: str = "教务部门 Academic Office") -> tuple[str, str]:
    """返回 (subject, html)。"""
    sid = _esc(student.get("student_id", ""))
    grade = _esc(_norm_grade(student.get("grade", "")))
    klass = _esc(student.get("class", ""))
    school = _esc(student.get("school", ""))

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

    subject = f"[缺交作业通知] Missing Work Notification — 学生ID {sid} / Grade {grade} / Class {klass}"

    body = f"""\
<div style="font-family:'Segoe UI','Microsoft YaHei',Arial,sans-serif; background:#f6f8fa; padding:24px;">
  <div style="max-width:680px; margin:0 auto; background:#ffffff; border:1px solid #e5e7eb; border-radius:6px; overflow:hidden;">
    <div style="padding:18px 24px; background:#1f4e79; color:#ffffff; font-size:17px; font-weight:bold;">
      缺交作业通知 Missing Work Notification
    </div>
    <div style="padding:24px;">
      <p style="margin:0 0 12px; font-size:14px; color:#333;">尊敬的家长 / Dear Parent，</p>
      <p style="margin:0 0 16px; font-size:14px; color:#333; line-height:1.6;">
        您好！以下是贵子女近期缺交作业的记录，请您知悉并关注。<br/>
        Please find below the recent missing work records for your child. Kindly review and follow up.
      </p>

      <div style="margin:0 0 20px; font-size:14px; color:#333; line-height:1.8;">
        <strong>学生信息 / Student Info</strong><br/>
        学生编号 Student ID：{sid}<br/>
        年级 Grade：{grade}<br/>
        班级 Class：{klass}
      </div>

      <div style="margin:0 0 20px;">
        <strong style="font-size:14px; color:#333;">作业异常列表 / Missing Work List</strong>
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

      <p style="margin:0; font-size:14px; color:#333;">谢谢 / Thank you,</p>
      <p style="margin:0; font-size:14px; color:#333;">{school} · {_esc(sender_display_name)}</p>
    </div>
  </div>
</div>"""

    return subject, body
