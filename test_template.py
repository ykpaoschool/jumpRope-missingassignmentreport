import sys

sys.path.insert(0, ".")

from app.email_template import render_email

student = {
    "student_id": "24311",
    "student_name": "San Zhang",
    "grade": "08",
    "class": "2031",
    "school": "YK Pao",
    "parent_email": "parent@example.com",
    "items": [
        {"course": "8 MATH 数学", "teacher": "Sue Li", "title": "1.1.1 HW", "due_date": "2026-09-08", "code": "M"},
        {"course": "8 MATH MODELLING 数学建模", "teacher": "Ann Xue, Freya Zhang", "title": "Mock Test-0903", "due_date": "2026-09-03", "code": "M"},
    ],
}

URL = "https://shorturl.myykps.cn/ms-pfswt"
SIG = "包校初中部学术办公室/YK Pao Middle School Academic Affairs Office"
MAIL = "hq-aao@ykpaoschool.cn"

# 场景 1：完整渲染，字段与固定文案齐全
subject, html = render_email(student, SIG, MAIL, URL)
print("SUBJECT:", subject)
assert "8 MATH 数学" in html
assert "2026-09-08" in html
assert "Missing Assignments Notification" in subject
assert "缺交作业通知 Missing Assignments Notification" in html
assert "学生姓名 Student Name：San Zhang" in html
assert "学号 Student ID：24311" in html
assert "Grade Level：8" in html
assert "班级 Class" not in html, "新模板的学生信息不再包含班级"
assert "作业异常列表 / Missing Assignment List" in html
assert "Section Course Name" in html
assert "X: Missing (did not submit but should have) 未提交（应当提交但未上交）" in html
assert "M: Missing Work" not in html, "M 行不再发提醒邮件，图例里不再解释 M"
assert "Incomplete Work" not in html
assert f'href="{URL}"' in html
assert "查看未按时提交作业处理程序" in html
assert "请注意：尽管形成性评价的结果不会直接计入学生的学业表现等级" in html
assert "如您有任何疑问，请联系相关学科教师。" in html
assert "可联系相关学科教师" not in html
# 段落里的英文跨行书写，断言前先把空白压平
flat = " ".join(html.split())
assert "formative evidence doesn" in flat and "summative assessments." in flat
assert "contact the relevant subject teacher(s)" in flat
assert SIG in html and MAIL in html

# 场景 2：姓名为空 → 整行不显示，不留空标签
_, html_no_name = render_email({**student, "student_name": ""}, SIG, MAIL, URL)
assert "学生姓名" not in html_no_name
assert "学号 Student ID：24311" in html_no_name

# 场景 3：未配置跳转地址 → 退化为带下划线的普通文字，不产生死链
_, html_no_url = render_email(student, SIG, MAIL, "")
assert "<a href" not in html_no_url
assert 'text-decoration:underline;">此处</span>' in html_no_url

# 场景 4：所有动态字段均做 HTML 转义
_, html_esc = render_email({**student, "student_name": '<b>"x"</b>'}, SIG, MAIL, URL)
assert "<b>" not in html_esc and "&lt;b&gt;" in html_esc

print("OK: template renders bilingual content")
