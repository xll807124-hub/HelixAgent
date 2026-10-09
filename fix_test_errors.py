import pathlib

files = [
    'tests/unit/tools/test_executor.py',
    'tests/unit/action_loop/test_execution_loop.py'
]

for filepath in files:
    p = pathlib.Path(filepath)
    content = p.read_text(encoding='utf-8')
    
    # 替换 result.action.error 为 result.action.metadata.get("error")
    content = content.replace('result.action.error', 'result.action.metadata.get("error")')
    
    # 替换 action.error 为 action.metadata.get("error")
    content = content.replace('action.error', 'action.metadata.get("error")')
    
    p.write_text(content, encoding='utf-8')
    print(f"Fixed {filepath}")

print("All test files fixed")
