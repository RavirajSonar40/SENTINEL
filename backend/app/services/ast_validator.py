"""Multi-language AST and Compiler Syntax Validator for Phase 11.

Uses real compilers and parsers to validate code syntax before patch application:
- Python: ast.parse
- JSON: json.loads
- YAML: yaml.safe_load
- JavaScript: Node.js (--check)
- TypeScript: tsc / npx tsc (--noEmit)
- Go: gofmt -e
- Shell: bash -n or shellcheck
- Rust: rustc

Guarantees zero heuristic brace-counting fallbacks: if a required compiler is missing,
validation fails closed with an explicit descriptive error.
"""
import ast
import json
import os
import sys
import shutil
import subprocess
import tempfile
from typing import Tuple, Optional
import yaml
import logging

logger = logging.getLogger("sentinel.ast_validator")


def validate_python_syntax(code: str) -> Tuple[bool, Optional[str]]:
    """Validate Python code using standard library ast module."""
    try:
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        return False, f"Python SyntaxError at line {e.lineno}, offset {e.offset}: {e.msg}"
    except Exception as e:
        return False, f"Python parse error: {str(e)}"


def validate_json_syntax(code: str) -> Tuple[bool, Optional[str]]:
    """Validate JSON code using standard library json module."""
    try:
        json.loads(code)
        return True, None
    except json.JSONDecodeError as e:
        return False, f"JSON DecodeError at line {e.lineno}, col {e.colno}: {e.msg}"
    except Exception as e:
        return False, f"JSON parse error: {str(e)}"


def validate_yaml_syntax(code: str) -> Tuple[bool, Optional[str]]:
    """Validate YAML code using PyYAML safe_load."""
    try:
        yaml.safe_load(code)
        return True, None
    except yaml.YAMLError as e:
        return False, f"YAML SyntaxError: {str(e)}"
    except Exception as e:
        return False, f"YAML parse error: {str(e)}"


def validate_javascript_syntax(code: str) -> Tuple[bool, Optional[str]]:
    """Validate JavaScript syntax using Node.js runtime compiler check."""
    node_bin = shutil.which("node") or shutil.which("node.exe")
    if not node_bin:
        return False, "JavaScript syntax validator unavailable: 'node' runtime is not installed in environment"

    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False, encoding="utf-8") as tf:
        tf.write(code)
        tf_path = tf.name

    try:
        res = subprocess.run(
            [node_bin, "--check", tf_path],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            return False, f"JavaScript SyntaxError: {err[:400]}"
        return True, None
    except subprocess.TimeoutExpired:
        return False, "JavaScript syntax validation timed out after 10s"
    except Exception as e:
        return False, f"JavaScript syntax validation error: {str(e)}"
    finally:
        if os.path.exists(tf_path):
            os.unlink(tf_path)


def validate_typescript_syntax(code: str, is_tsx: bool = False) -> Tuple[bool, Optional[str]]:
    """Validate TypeScript syntax using official TypeScript compiler (typescript/bin/tsc via node)."""
    node_bin = shutil.which("node") or shutil.which("node.exe")

    # Locate typescript/bin/tsc
    possible_tsc_js = [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "sentinel-ui", "node_modules", "typescript", "bin", "tsc"),
        os.path.join(os.getcwd(), "node_modules", "typescript", "bin", "tsc"),
        os.path.join(os.getcwd(), "..", "sentinel-ui", "node_modules", "typescript", "bin", "tsc"),
    ]

    tsc_js = None
    for p in possible_tsc_js:
        p_abs = os.path.abspath(p)
        if os.path.exists(p_abs):
            tsc_js = p_abs
            break

    if not node_bin or not tsc_js:
        return False, "TypeScript syntax validator unavailable: 'node' runtime or 'typescript' compiler is not installed in environment"

    suffix = ".tsx" if is_tsx else ".ts"
    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False, encoding="utf-8") as tf:
        tf.write(code)
        tf_path = tf.name

    try:
        cmd = [node_bin, tsc_js, "--noEmit", "--skipLibCheck", "--target", "es2022", "--jsx", "react-jsx" if is_tsx else "preserve", tf_path]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        if res.returncode != 0:
            err = res.stdout.strip() or res.stderr.strip()
            return False, f"TypeScript SyntaxError: {err[:400]}"
        return True, None
    except subprocess.TimeoutExpired:
        return False, "TypeScript syntax validation timed out after 10s"
    except Exception as e:
        return False, f"TypeScript syntax validation error: {str(e)}"
    finally:
        if os.path.exists(tf_path):
            os.unlink(tf_path)


def validate_go_syntax(code: str) -> Tuple[bool, Optional[str]]:
    """Validate Go syntax using official gofmt tool."""
    gofmt = shutil.which("gofmt") or shutil.which("gofmt.exe")
    if not gofmt:
        return False, "Go syntax validator unavailable: 'gofmt' is not installed in environment"

    with tempfile.NamedTemporaryFile(suffix=".go", mode="w", delete=False, encoding="utf-8") as tf:
        tf.write(code)
        tf_path = tf.name

    try:
        res = subprocess.run([gofmt, "-e", tf_path], capture_output=True, text=True, timeout=10, shell=False)
        if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            return False, f"Go SyntaxError: {err[:400]}"
        return True, None
    except subprocess.TimeoutExpired:
        return False, "Go syntax validation timed out after 10s"
    except Exception as e:
        return False, f"Go syntax validation error: {str(e)}"
    finally:
        if os.path.exists(tf_path):
            os.unlink(tf_path)


def validate_shell_syntax(code: str) -> Tuple[bool, Optional[str]]:
    """Validate Shell script syntax using bash -n or shellcheck."""
    shellcheck = shutil.which("shellcheck") or shutil.which("shellcheck.exe")
    bash = shutil.which("bash") or shutil.which("bash.exe")

    if shellcheck:
        with tempfile.NamedTemporaryFile(suffix=".sh", mode="w", delete=False, encoding="utf-8") as tf:
            tf.write(code)
            tf_path = tf.name
        try:
            res = subprocess.run([shellcheck, "-s", "bash", tf_path], capture_output=True, text=True, timeout=10, shell=False)
            if res.returncode != 0:
                err = res.stdout.strip() or res.stderr.strip()
                return False, f"Shellcheck SyntaxError: {err[:400]}"
            return True, None
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    if bash:
        with tempfile.NamedTemporaryFile(suffix=".sh", mode="w", delete=False, encoding="utf-8") as tf:
            tf.write(code)
            tf_path = tf.name
        try:
            res = subprocess.run([bash, "-n", tf_path], capture_output=True, text=True, timeout=10, shell=False)
            if res.returncode != 0:
                err = res.stderr.strip() or res.stdout.strip()
                return False, f"Shell SyntaxError: {err[:400]}"
            return True, None
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    return False, "Shell syntax validator unavailable: neither 'shellcheck' nor 'bash' is installed in environment"


def validate_rust_syntax(code: str) -> Tuple[bool, Optional[str]]:
    """Validate Rust syntax using rustc compiler check."""
    rustc = shutil.which("rustc") or shutil.which("rustc.exe")
    if not rustc:
        return False, "Rust syntax validator unavailable: 'rustc' is not installed in environment"

    with tempfile.NamedTemporaryFile(suffix=".rs", mode="w", delete=False, encoding="utf-8") as tf:
        tf.write(code)
        tf_path = tf.name

    try:
        res = subprocess.run(
            [rustc, "--emit=metadata", "-o", os.devnull, tf_path],
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
        )
        if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            return False, f"Rust SyntaxError: {err[:400]}"
        return True, None
    except subprocess.TimeoutExpired:
        return False, "Rust syntax validation timed out after 15s"
    except Exception as e:
        return False, f"Rust syntax validation error: {str(e)}"
    finally:
        if os.path.exists(tf_path):
            os.unlink(tf_path)


def validate_code_syntax(file_path: str, code: str) -> Tuple[bool, Optional[str]]:
    """Determine file type and validate its syntax using the guaranteed real compiler/parser."""
    if not code or not code.strip():
        return True, None

    ext = os.path.splitext(file_path)[1].lower()

    if ext in (".py", ".pyw"):
        return validate_python_syntax(code)
    elif ext in (".json", ".jsonc"):
        return validate_json_syntax(code)
    elif ext in (".yaml", ".yml"):
        return validate_yaml_syntax(code)
    elif ext in (".js", ".mjs", ".cjs"):
        return validate_javascript_syntax(code)
    elif ext in (".ts",):
        return validate_typescript_syntax(code, is_tsx=False)
    elif ext in (".tsx", ".jsx"):
        return validate_typescript_syntax(code, is_tsx=True)
    elif ext in (".go",):
        return validate_go_syntax(code)
    elif ext in (".sh", ".bash"):
        return validate_shell_syntax(code)
    elif ext in (".rs",):
        return validate_rust_syntax(code)
    elif ext in (".md", ".txt", ".csv", ".rst", ".html", ".htm", ".css", ".sql", ".dockerfile") or os.path.basename(file_path).lower() in ("dockerfile", "makefile", "license"):
        # Plain text / declarative configuration formats without dedicated executable AST compilers
        return True, None
    else:
        # Recognized source extension with unconfigured parser
        return True, None
