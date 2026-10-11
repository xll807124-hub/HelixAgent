import pathlib

# 修复 executor.py 中的 error 字段
p = pathlib.Path('src/tools/executor.py')
content = p.read_text(encoding='utf-8')

# 替换所有 "error": 为在 metadata 中存储
lines = content.split('\n')
new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    # 查找包含 "status_projection": ActionStatus.FAILED 的行
    if (  # noqa: E501
        '"status_projection": ActionStatus.FAILED,' in line
        or '"status_projection": ActionStatus.WAITING_APPROVAL,' in line
    ):
        new_lines.append(line)
        i += 1
        # 检查下一行是否有 error 字段
        if i < len(lines) and '"error":' in lines[i]:
            # 替换为 metadata 格式
            error_line = lines[i]
            indent = len(error_line) - len(error_line.lstrip())
            error_value = error_line.split('"error":', 1)[1].strip()
            # 添加 metadata 替换
            new_lines.append(' ' * indent + '"metadata": {')
            new_lines.append(' ' * indent + '    **action.metadata,')
            new_lines.append(' ' * indent + '    "error": ' + error_value)
            new_lines.append(' ' * indent + '},')
            i += 1
        continue
    new_lines.append(line)
    i += 1

p.write_text('\n'.join(new_lines), encoding='utf-8')
print("Fixed executor.py error fields")
