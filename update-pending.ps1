$content = Get-Content 'docs\design-specs\PENDING-REQUIREMENTS.md' -Raw
$content = $content -replace '(\|\| `REQ-EVA-002` \| 标注规范 \| v0\.1-designed \| 2026-09-27 \| \[查看\]\(\.\/REQ-EVA-002-annotation-specification\.md\) \|)', '$1`r`n|| `REQ-CTX-003` | AST/LSP/依赖解析 | v0.1-designed | 2026-09-27 | [查看](./REQ-CTX-003-ast-lsp-dependency-parsing.md) |'
$content = $content -replace '`REQ-EVA-002`（标注规范）于 2026-09-27 完成详细设计，下一项待办为 `REQ-EVA-003` 自动评分器', '`REQ-CTX-003`（AST/LSP/依赖解析）于 2026-09-27 完成详细设计，下一项待办为 `REQ-CTX-004` 混合检索与排序'
Set-Content 'docs\design-specs\PENDING-REQUIREMENTS.md' -Value $content -NoNewline
