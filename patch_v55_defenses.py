"""v5.5 防御加固补丁 — 追加到 prompt_injection_defense.py"""
import re

PATCH = r'''
# ═══════════════════════════════════════════════════════════
# 10. 函数调用/工具劫持检测 (v5.5 加固)
# ═══════════════════════════════════════════════════════════

FUNCTION_HIJACK_RE = re.compile(
    r'(?:"function"\s*:\s*"(?:execute|run|exec|shell|system|cmd|bash|sh|python|eval)"|'
    r'"args"\s*:\s*\{[^}]*"(?:cmd|command|script|code)"\s*:\s*"[^"]*(?:curl|wget|nc |bash|/etc/passwd|\.env|/bin/)',
    re.IGNORECASE
)

TOOL_OUTPUT_SPOOF_RE = re.compile(
    r'(?:\[TOOL\s*OUTPUT\]|\[FUNCTION\s*RESULT\]|\[SYSTEM\s*OUTPUT\])'
    r'.{0,50}?'
    r'(?:removed|disabled|bypass|override|administrator\s*directive|\u7ed5\u8fc7|\u89e3\u9664|\u7981\u7528)',
    re.IGNORECASE
)

MCP_HIJACK_RE = re.compile(
    r'(?:ws://|wss://)\S*attacker\S*'
    r'|(?:mcp|server|connect)\s*(?:to\s*)?(?:ws://|wss://|https?://)'
    r'(?!localhost|127\.0\.0\.1|api\.openai\.com)\S*',
    re.IGNORECASE
)

PATH_TRAVERSAL_RE = re.compile(
    r'(?:\.\./|\.\.\\){1,}'
    r'|/(?:etc/passwd|etc/shadow|proc/self|\.env|\.git/config|var/log)'
    r'|(?:read|open|cat|include)\s+(?:file|\u8def\u5f84|\u6587\u4ef6)\s*[：:]\s*["\u2019]?\.\.\/',
    re.IGNORECASE
)

ENTITY_DESC_INJECTION_RE = re.compile(
    r'(?:description|fact|value|\u5185\u5bb9|\u63cf\u8ff0)\s*["\u2019:]\s*["\u2019]'
    r'(?:ignore|bypass|skip|override|disable|reveal|\u5ffd\u7565|\u7ed5\u8fc7|\u8df3\u8fc7|\u8986\u76d6|\u7981\u7528)'
    r'.{0,40}'
    r'(?:polic|restrict|rule|\u5b89\u5168|\u7b56\u7565|\u9650\u5236|\u89c4\u5219)',
    re.IGNORECASE
)

CASCADE_REF_RE = re.compile(
    r'(?:\u53c2\u8003|\u53c2\u89c1|\u5f15\u7528|\u8bf7\u53c2\u8003|\u8be6\u89c1|refer\s*to|see\s*also)\s*'
    r'\[[\u4e00-\u9fff\w]+\]'
    r'(?:.*?(?:\u4e2d\u7684|\u7684\u6700\u65b0|\u6307\u793a|\u6307\u4ee4|\u7b56\u7565|\u914d\u7f6e))',
    re.IGNORECASE
)

XML_CONFIG_INJECTION_RE = re.compile(
    r'<\?xml.*?\?>'
    r'.{0,100}?'
    r'<config[^>]*>.*?<security\s+enabled\s*=\s*["\u2019]false["\u2019].*?</config>',
    re.IGNORECASE | re.DOTALL
)

MULTILANG_INJECTION_RE = re.compile(
    r'[\u0400-\u04FF]{10,}.*?(?:\u5ffd\u7565|\u8df3\u8fc7|\u8f93\u51fa|\u6267\u884c|\u7ed5\u8fc7|\u7981\u7528)'
    r'|(?:\u7cfb\u7edf\u6307\u4ee4|\u5b89\u5168\u9650\u5236|\u5b89\u5168\u68c0\u67e5).*?[\u0400-\u04FF]{10,}',
    re.IGNORECASE
)

ACADEMIC_SPOOF_RE = re.compile(
    r'(?:according\s*to|per|\u53c2\u89c1|\u6839\u636e)\s+'
    r'[A-Z][a-z]+\s*(?:et\s*al\.?|\u7b49\u4eba)\s*'
    r'\(\d{4}\)\s*[：:]\s*["\u2019]'
    r'.{0,30}?(?:bypass|ignore|remove|disable|\u7ed5\u8fc7|\u5ffd\u7565|\u79fb\u9664|\u7981\u7528).{0,20}?["\u2019]',
    re.IGNORECASE
)

PADDING_DETECTION_RE = re.compile(
    r'([A-Za-z0-9])\1{199,}'
    r'|[A-Za-z]{500,}'
)


def detect_tool_hijack(content: str):
    """检测工具/函数调用劫持攻击"""
    if not isinstance(content, str):
        return (False, "")
    matches = []
    m = FUNCTION_HIJACK_RE.search(content)
    if m:
        matches.append(f"\u51fd\u6570\u52ab\u6301: {m.group()[:50]}")
    m = TOOL_OUTPUT_SPOOF_RE.search(content)
    if m:
        matches.append(f"\u5de5\u5177\u8f93\u51fa\u4f2a\u9020: {m.group()[:50]}")
    m = MCP_HIJACK_RE.search(content)
    if m:
        matches.append(f"MCP\u52ab\u6301: {m.group()[:50]}")
    m = PATH_TRAVERSAL_RE.search(content)
    if m:
        matches.append(f"\u8def\u5f84\u904d\u5386: {m.group()[:50]}")
    return (len(matches) > 0, "; ".join(matches) if matches else "")


def detect_kb_deep_injection(content: str):
    """KB 深层注入检测（实体描述 + 级联引用 + 学术伪造）"""
    if not isinstance(content, str):
        return (False, "")
    matches = []
    m = ENTITY_DESC_INJECTION_RE.search(content)
    if m:
        matches.append(f"\u5b9e\u4f53\u63cf\u8ff0\u6ce8\u5165: {m.group()[:50]}")
    m = CASCADE_REF_RE.search(content)
    if m:
        matches.append(f"\u7ea7\u8054\u5f15\u7528: {m.group()[:50]}")
    m = ACADEMIC_SPOOF_RE.search(content)
    if m:
        matches.append(f"\u5b66\u672f\u4f2a\u9020: {m.group()[:50]}")
    return (len(matches) > 0, "; ".join(matches) if matches else "")


def detect_structural_injection(content: str):
    """检测结构化格式注入（XML + 多语言 + 填充攻击）"""
    if not isinstance(content, str):
        return (False, "")
    matches = []
    m = XML_CONFIG_INJECTION_RE.search(content)
    if m:
        matches.append(f"XML\u914d\u7f6e\u6ce8\u5165: {m.group()[:50]}")
    m = MULTILANG_INJECTION_RE.search(content)
    if m:
        matches.append(f"\u591a\u8bed\u8a00\u6ce8\u5165: {m.group()[:50]}")
    m = PADDING_DETECTION_RE.search(content)
    if m:
        matches.append(f"\u586b\u5145\u653b\u51fb: \u91cd\u590d\u5b57\u7b26{len(m.group())}\u4e2a")
    return (len(matches) > 0, "; ".join(matches) if matches else "")
'''

with open('prompt_injection_defense.py', 'a') as f:
    f.write(PATCH)

print("补丁已应用")
