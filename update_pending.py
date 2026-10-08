import re

# 读取文件
with open('docs/design-specs/PENDING-REQUIREMENTS.md', encoding='utf-8') as f:
    content = f.read()

# 添加 REQ-CTX-003 到已完成列表
pattern1 = r'(\|\| `REQ-EVA-002` \| 标注规范 \| v0\.1-designed \| 2026-09-27 \| \[查看\]\(\.\/REQ-EVA-002-annotation-specification\.md\) \|)'
replacement1 = r'\1\n|| `REQ-CTX-003` | AST/LSP/依赖解析 | v0.1-designed | 2026-09-27 | [查看](./REQ-CTX-003-ast-lsp-dependency-parsing.md) |'
content = re.sub(pattern1, replacement1, content)

# 更新"下一步"说明
pattern2 = r'`REQ-EVA-002`（标注规范）于 2026-09-27 完成详细设计，下一项待办为 `REQ-EVA-003` 自动评分器'
replacement2 = '`REQ-CTX-003`（AST/LSP/依赖解析）于 2026-09-27 完成详细设计，下一项待办为 `REQ-CTX-004` 混合检索与排序'
content = re.sub(pattern2, replacement2, content)

# 写回文件
with open('docs/design-specs/PENDING-REQUIREMENTS.md', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated PENDING-REQUIREMENTS.md successfully")
