"""webui.py 페이지 추출 — 필요한 import 를 자유변수 분석으로 산출한다.

리포지토리 루트에서 실행한다. webui 로컬 함수·전역을 참조하는 페이지는 **거부**한다
(먼저 ui/components.py 같은 공용 모듈로 올려야 한다).

수동으로 import 를 적으면 누락이 런타임에만 드러난다 (4단계 ml_predict 사례).
"""
import ast, builtins, pathlib, sys, textwrap

WEBUI = pathlib.Path('stock_analyzer/webui.py')


def _top_context(tree):
    funcs, assigned, imports = set(), set(), {}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef):
            funcs.add(n.name)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            for t in ast.walk(n):
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                    assigned.add(t.id)
        elif isinstance(n, ast.Import):
            for a in n.names:
                imports[a.asname or a.name.split('.')[0]] = ('plain', a.name, a.asname)
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                imports[a.asname or a.name] = ('from', n.module, a.name)
    return funcs, assigned, imports


class Free(ast.NodeVisitor):
    def __init__(self):
        self.bound, self.free = set(), set()

    def visit_FunctionDef(self, n):
        self.bound.add(n.name)
        args = n.args
        for a in args.args + args.kwonlyargs + args.posonlyargs:
            self.bound.add(a.arg)
        if args.vararg:
            self.bound.add(args.vararg.arg)
        if args.kwarg:
            self.bound.add(args.kwarg.arg)
        self.generic_visit(n)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Name(self, n):
        (self.bound if isinstance(n.ctx, ast.Store) else self.free).add(n.id)

    def visit_ExceptHandler(self, n):
        if n.name:
            self.bound.add(n.name)
        self.generic_visit(n)


def extract(names, module_path, docstring):
    src = WEBUI.read_text()
    tree = ast.parse(src)
    funcs, assigned, imports = _top_context(tree)
    lines = src.split('\n')

    blocks, needed = [], set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
            block = '\n'.join(lines[start:node.end_lineno])
            blocks.append((node.name, block))
            f = Free()
            f.visit(node)
            free = f.free - f.bound - set(dir(builtins)) - set(names)
            local = sorted(free & (funcs | assigned))
            if local:
                sys.exit(f"{node.name}: webui 로컬 의존 {local} — 먼저 공용 모듈로 옮겨라")
            unknown = free - set(imports)
            if unknown:
                print(f"  주의 {node.name}: 미확인 {sorted(unknown)}")
            needed |= free & set(imports)

    assert len(blocks) == len(names), f"블록 누락: {set(names) - {b[0] for b in blocks}}"

    plain, froms = [], {}
    for name in sorted(needed):
        kind, mod, alias = imports[name]
        if kind == 'plain':
            plain.append(f"import {mod}" + (f" as {alias}" if alias else ""))
        else:
            froms.setdefault(mod, set()).add(alias)
    header = [f'"""{docstring}', '',
              '`webui.py` 분해 — 페이지 단위 (CLAUDE.md §6-10). 분리 후 **렌더 함수를 직접',
              '호출**해 확인한다: ast 파싱·import·HTTP 200 은 화면 결함을 잡지 못한다 (§13.9a).',
              '"""', '', 'from __future__ import annotations', '']
    header += sorted(plain) + ['']
    for mod in sorted(froms):
        header.append(f"from {mod} import {', '.join(sorted(froms[mod]))}")
    body = '\n\n\n'.join(b for _, b in blocks)
    pathlib.Path(module_path).write_text('\n'.join(header) + '\n\n\n' + body.rstrip() + '\n')

    # webui 에서 제거
    for name, block in blocks:
        assert block in src, name
        src = src.replace(block + '\n', '', 1)
    WEBUI.write_text(src)
    print(f"  → {module_path}: {sum(b.count(chr(10)) for _, b in blocks)}줄")


def _cli() -> int:
    """CLI: extract_webui_page.py <module> "<docstring>" <render_fn> [render_fn ...]"""
    if len(sys.argv) < 4:
        print(__doc__)
        print('사용법: python scripts/extract_webui_page.py <모듈명> "<docstring>" '
              '<render_함수> [...]')
        return 2
    module, doc, names = sys.argv[1], sys.argv[2], sys.argv[3:]
    extract(names, f"stock_analyzer/ui/pages/{module}.py", doc)
    print("남은 작업: webui.py 에 import 추가 → 4단 검증 (§13.9a)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
