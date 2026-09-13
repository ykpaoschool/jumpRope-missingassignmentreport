import sys

sys.path.insert(0, ".")

from app.email_template import render_email

student = {
    "student_id": "24311",
    "grade": "08",
    "class": "2031",
    "school": "YK Pao",
    "parent_email": "parent@example.com",
    "items": [
        {"course": "8 MATH 数学", "teacher": "Sue Li", "title": "1.1.1 HW", "due_date": "2026-09-08", "code": "M"},
        {"course": "8 MATH MODELLING 数学建模", "teacher": "Ann Xue, Freya Zhang", "title": "Mock Test-0903", "due_date": "2026-09-03", "code": "M"},
    ],
}

subject, html = render_email(student, "教务部门 Academic Office")
print("SUBJECT:", subject)
assert "8 MATH 数学" in html
assert "2026-09-08" in html
assert "Grade：8" in html
assert "Class：2031" in html
assert "Sue Li" in html
assert "Section Course Name" in html
print("OK: template renders bilingual content")
