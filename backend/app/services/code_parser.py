"""Code-aware parsing and chunking — extracts functions, classes, symbols from files."""
import re
import hashlib
from typing import List, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class CodeChunk:
    """A semantically meaningful chunk of code."""
    id: str
    file_path: str
    content: str
    chunk_type: str  # function, class, method, module, comment, import
    symbol_name: Optional[str] = None
    parent_symbol: Optional[str] = None
    line_start: int = 0
    line_end: int = 0
    language: str = "unknown"
    imports: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            raw = f"{self.file_path}:{self.symbol_name or self.chunk_type}:{self.line_start}"
            self.id = hashlib.sha256(raw.encode()).hexdigest()[:16]


# Language detection patterns
LANG_PATTERNS = {
    "python": [r"\.py$", r"def\s+\w+\(", r"class\s+\w+"],
    "javascript": [r"\.js$", r"\.jsx$", r"function\s+\w+\(|const\s+\w+\s*=\s*\("],
    "typescript": [r"\.ts$", r"\.tsx$", r":\s*(string|number|boolean|void)"],
    "go": [r"\.go$", r"func\s+\w+\(", r"package\s+\w+"],
    "java": [r"\.java$", r"public\s+class\s+"],
    "rust": [r"\.rs$", r"fn\s+\w+\(", r"impl\s+"],
    "ruby": [r"\.rb$", r"def\s+\w+", r"class\s+\w+"],
    "php": [r"\.php$", r"function\s+\w+\(", r"class\s+\w+"],
}


def detect_language(file_path: str, content: str = "") -> str:
    """Detect programming language from file path and content."""
    for lang, patterns in LANG_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, file_path):
                return lang
            if content and re.search(pat, content[:500]):
                return lang
    return "unknown"


def parse_file(file_path: str, content: str) -> List[CodeChunk]:
    """Parse a source file into code-aware chunks."""
    lang = detect_language(file_path, content)

    parser_map = {
        "python": _parse_python,
        "javascript": _parse_js,
        "typescript": _parse_js,
        "go": _parse_go,
        "java": _parse_java,
        "rust": _parse_rust,
    }

    parser = parser_map.get(lang, _parse_generic)
    chunks = parser(file_path, content, lang)

    # Always add a module-level chunk
    lines = content.split("\n")
    chunks.insert(0, CodeChunk(
        id="",
        file_path=file_path,
        content=content[:2000] if len(content) > 2000 else content,
        chunk_type="module",
        symbol_name=file_path.split("/")[-1],
        line_start=1,
        line_end=len(lines),
        language=lang,
        imports=[],
        metadata={"total_lines": len(lines), "total_chars": len(content)},
    ))

    return chunks


def _parse_python(file_path: str, content: str, lang: str) -> List[CodeChunk]:
    """Parse Python files — extract functions, classes, methods."""
    chunks = []
    lines = content.split("\n")
    current_imports = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Track imports
        if line.strip().startswith("import ") or line.strip().startswith("from "):
            current_imports.append(line.strip())
            i += 1
            continue

        # Function definition
        match = re.match(r"^(\s*)def\s+(\w+)\s*\((.*)\)", line)
        if match:
            indent = len(match.group(1))
            name = match.group(2)
            params = match.group(3)
            start = i
            body_lines = [line]
            i += 1
            while i < len(lines) and (lines[i].strip() == "" or len(lines[i]) - len(lines[i].lstrip()) > indent):
                body_lines.append(lines[i])
                i += 1
            chunks.append(CodeChunk(
                id="",
                file_path=file_path,
                content="\n".join(body_lines),
                chunk_type="function",
                symbol_name=name,
                line_start=start + 1,
                line_end=i,
                language=lang,
                imports=list(current_imports),
                metadata={"params": params, "indent": indent},
            ))
            continue

        # Class definition
        match = re.match(r"^(\s*)class\s+(\w+)\s*[\(:]", line)
        if match:
            indent = len(match.group(1))
            name = match.group(2)
            start = i
            body_lines = [line]
            i += 1
            while i < len(lines) and (lines[i].strip() == "" or len(lines[i]) - len(lines[i].lstrip()) > indent):
                body_lines.append(lines[i])
                i += 1
            chunks.append(CodeChunk(
                id="",
                file_path=file_path,
                content="\n".join(body_lines),
                chunk_type="class",
                symbol_name=name,
                line_start=start + 1,
                line_end=i,
                language=lang,
                imports=list(current_imports),
                metadata={"indent": indent},
            ))
            continue

        i += 1

    return chunks


def _parse_js(file_path: str, content: str, lang: str) -> List[CodeChunk]:
    """Parse JS/TS files — extract functions, classes, arrow functions, exports."""
    chunks = []
    lines = content.split("\n")
    current_imports = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Track imports
        if stripped.startswith("import ") or stripped.startswith("require("):
            current_imports.append(stripped)
            i += 1
            continue

        # Function declaration: function name() {}, export default function name() {}
        match = re.match(r"^(export\s+(default\s+)?)?(async\s+)?function\s+(\w+)\s*\(", stripped)
        if match:
            name = match.group(4)
            start = i
            brace_count = 0
            body_lines = []
            found_open = False
            while i < len(lines):
                body_lines.append(lines[i])
                for ch in lines[i]:
                    if ch == "{":
                        brace_count += 1
                        found_open = True
                    elif ch == "}":
                        brace_count -= 1
                if found_open and brace_count <= 0:
                    i += 1
                    break
                i += 1
            chunks.append(CodeChunk(
                id="",
                file_path=file_path,
                content="\n".join(body_lines),
                chunk_type="function",
                symbol_name=name,
                line_start=start + 1,
                line_end=i,
                language=lang,
                imports=list(current_imports),
            ))
            continue

        # Arrow function: const name = () => {}, export const name = () => {}
        match = re.match(r"^(export\s+(default\s+)?)?(const|let|var)\s+(\w+)\s*=\s*(async\s*)?(\(|[a-zA-Z0-9_]+\s*=>)", stripped)
        if match:
            name = match.group(4)
            start = i
            brace_count = 0
            body_lines = []
            found_open = False
            while i < len(lines):
                body_lines.append(lines[i])
                for ch in lines[i]:
                    if ch == "{":
                        brace_count += 1
                        found_open = True
                    elif ch == "}":
                        brace_count -= 1
                if found_open and brace_count <= 0:
                    i += 1
                    break
                i += 1
            chunks.append(CodeChunk(
                id="",
                file_path=file_path,
                content="\n".join(body_lines),
                chunk_type="function",
                symbol_name=name,
                line_start=start + 1,
                line_end=i,
                language=lang,
                imports=list(current_imports),
            ))
            continue

        i += 1

    return chunks


def _parse_go(file_path: str, content: str, lang: str) -> List[CodeChunk]:
    """Parse Go files — extract functions, methods, structs."""
    chunks = []
    lines = content.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]

        # func name() {}
        match = re.match(r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(", line)
        if match:
            name = match.group(1)
            start = i
            brace_count = 0
            body_lines = []
            found_open = False
            while i < len(lines):
                body_lines.append(lines[i])
                for ch in lines[i]:
                    if ch == "{":
                        brace_count += 1
                        found_open = True
                    elif ch == "}":
                        brace_count -= 1
                if found_open and brace_count <= 0:
                    i += 1
                    break
                i += 1
            chunk_type = "method" if "(" in line else "function"
            chunks.append(CodeChunk(
                id="",
                file_path=file_path,
                content="\n".join(body_lines),
                chunk_type=chunk_type,
                symbol_name=name,
                line_start=start + 1,
                line_end=i,
                language=lang,
            ))
            continue

        i += 1

    return chunks


def _parse_java(file_path: str, content: str, lang: str) -> List[CodeChunk]:
    """Parse Java files — extract classes, methods."""
    chunks = []
    lines = content.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]

        # class/interface name {
        match = re.match(r"^(public|private|protected)?\s*(abstract\s+)?(class|interface|enum)\s+(\w+)", line)
        if match:
            name = match.group(4)
            start = i
            brace_count = 0
            body_lines = []
            found_open = False
            while i < len(lines):
                body_lines.append(lines[i])
                for ch in lines[i]:
                    if ch == "{":
                        brace_count += 1
                        found_open = True
                    elif ch == "}":
                        brace_count -= 1
                if found_open and brace_count <= 0:
                    i += 1
                    break
                i += 1
            chunks.append(CodeChunk(
                id="",
                file_path=file_path,
                content="\n".join(body_lines),
                chunk_type=match.group(3),
                symbol_name=name,
                line_start=start + 1,
                line_end=i,
                language=lang,
            ))
            continue

        # Method
        match = re.match(r"^\s+(public|private|protected)\s+\S+\s+(\w+)\s*\(", line)
        if match:
            name = match.group(2)
            start = i
            brace_count = 0
            body_lines = []
            found_open = False
            while i < len(lines):
                body_lines.append(lines[i])
                for ch in lines[i]:
                    if ch == "{":
                        brace_count += 1
                        found_open = True
                    elif ch == "}":
                        brace_count -= 1
                if found_open and brace_count <= 0:
                    i += 1
                    break
                i += 1
            chunks.append(CodeChunk(
                id="",
                file_path=file_path,
                content="\n".join(body_lines),
                chunk_type="method",
                symbol_name=name,
                line_start=start + 1,
                line_end=i,
                language=lang,
            ))
            continue

        i += 1

    return chunks


def _parse_rust(file_path: str, content: str, lang: str) -> List[CodeChunk]:
    """Parse Rust files — extract functions, impl blocks."""
    chunks = []
    lines = content.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]

        # fn name() {}
        match = re.match(r"^(pub\s+)?(async\s+)?fn\s+(\w+)\s*\(", line)
        if match:
            name = match.group(3)
            start = i
            brace_count = 0
            body_lines = []
            found_open = False
            while i < len(lines):
                body_lines.append(lines[i])
                for ch in lines[i]:
                    if ch == "{":
                        brace_count += 1
                        found_open = True
                    elif ch == "}":
                        brace_count -= 1
                if found_open and brace_count <= 0:
                    i += 1
                    break
                i += 1
            chunks.append(CodeChunk(
                id="",
                file_path=file_path,
                content="\n".join(body_lines),
                chunk_type="function",
                symbol_name=name,
                line_start=start + 1,
                line_end=i,
                language=lang,
            ))
            continue

        i += 1

    return chunks


def _parse_generic(file_path: str, content: str, lang: str) -> List[CodeChunk]:
    """Generic parser — split by blank lines into logical blocks."""
    chunks = []
    blocks = re.split(r"\n\s*\n", content)

    for idx, block in enumerate(blocks):
        block = block.strip()
        if not block or len(block) < 10:
            continue
        chunks.append(CodeChunk(
            id="",
            file_path=file_path,
            content=block,
            chunk_type="block",
            symbol_name=f"block_{idx}",
            line_start=content[:content.find(block)].count("\n") + 1,
            line_end=content[:content.find(block)].count("\n") + block.count("\n") + 1,
            language=lang,
        ))

    return chunks


# --- High-level ---

def chunk_repository(file_path: str, content: str) -> List[CodeChunk]:
    """Parse a single file and return chunks suitable for embedding."""
    return parse_file(file_path, content)


def chunk_batch(files: Dict[str, str], max_chunk_size: int = 1500) -> List[CodeChunk]:
    """Parse multiple files, split large chunks."""
    all_chunks = []
    for file_path, content in files.items():
        chunks = chunk_repository(file_path, content)
        for chunk in chunks:
            if len(chunk.content) > max_chunk_size:
                # Split large chunks
                lines = chunk.content.split("\n")
                mid = len(lines) // 2
                chunk.content = "\n".join(lines[:mid])
                chunk2 = CodeChunk(
                    id="",
                    file_path=chunk.file_path,
                    content="\n".join(lines[mid:]),
                    chunk_type=chunk.chunk_type,
                    symbol_name=f"{chunk.symbol_name}_part2",
                    parent_symbol=chunk.symbol_name,
                    line_start=mid + 1,
                    line_end=chunk.line_end,
                    language=chunk.language,
                    imports=chunk.imports,
                )
                all_chunks.append(chunk2)
            else:
                all_chunks.append(chunk)
    return all_chunks
