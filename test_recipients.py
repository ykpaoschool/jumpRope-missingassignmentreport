"""验证收件地址的拆分与校验（app/recipients.py）。

这个模块是「这封发给谁」与「界面说这列有多少邮箱」的共用规则，所以单独测。
"""

from app import recipients

# ---- 1. 分隔符：半角/全角逗号、分号、换行都认；空格不拆 ----
assert recipients.split("a@x.com,b@y.com") == ["a@x.com", "b@y.com"]
assert recipients.split("a@x.com;b@y.com") == ["a@x.com", "b@y.com"]
assert recipients.split("a@x.com; b@y.com, c@z.com") == ["a@x.com", "b@y.com", "c@z.com"]
assert recipients.split("a@x.com，b@y.com；c@z.com") == ["a@x.com", "b@y.com", "c@z.com"]
assert recipients.split("a@x.com\nb@y.com\r\n") == ["a@x.com", "b@y.com"]
# 空格不是分隔符：显示名形式的写法不该被切碎
assert recipients.split("Zhang <a@x.com>") == ["Zhang <a@x.com>"]

# ---- 2. 去空白、去空项、按小写去重（保留首次出现的大小写与顺序）----
assert recipients.split(" a@x.com ; A@X.com ;a@x.com") == ["a@x.com"]
assert recipients.split("A@x.com; a@X.com") == ["A@x.com"]
assert recipients.split("a@x.com,,;b@y.com") == ["a@x.com", "b@y.com"]
assert recipients.split(None) == [] and recipients.split("") == [] and recipients.split(" ,; ") == []

# ---- 3. join：写 To 头、界面展示与日志的规范形式 ----
assert recipients.join(["a@x.com", "b@y.com"]) == "a@x.com, b@y.com"  # 解析时手里已是列表
assert recipients.join("a@x.com;b@y.com") == "a@x.com, b@y.com"  # 原始文本先拆再拼
assert recipients.join("a@x.com") == "a@x.com"
assert recipients.join([]) == "" and recipients.join(None) == ""

# ---- 4. 非法片段判定（顺序保留、去重）----
assert recipients.invalid("N/A") == ["N/A"]
assert recipients.invalid("13800000000") == ["13800000000"]
assert recipients.invalid("a@x.com 已停用") == ["a@x.com 已停用"]  # 含空白 → 不是地址
assert recipients.invalid("a@b") == ["a@b"]  # 域名没有点
assert recipients.invalid("a@x.com;b@y.com") == []
assert recipients.invalid("a@x.com;N/A") == ["N/A"]
assert recipients.invalid("") == [] and recipients.invalid(" ") == []

# ---- 5. is_address 与 EMAIL_RE 同口径 ----
assert recipients.is_address("parent@example.com")
assert not recipients.is_address("parent@example")
assert not recipients.is_address("N/A")
assert not recipients.is_address("")

# ---- 6. split 只接受字符串：传列表会静默变成 "['a@x.com']" 这种垃圾地址，宁可当场报错 ----
try:
    recipients.split(["a@x.com"])
    raise AssertionError("split 收到列表时应当抛 TypeError")
except TypeError as e:
    assert "只接受字符串" in str(e), e

print("OK: recipients 拆分（半角/全角/换行/去重/空格不拆）与非法片段判定全部通过")
