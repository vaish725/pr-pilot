import fnmatch
import os
from dataclasses import dataclass, field
from typing import List

FOCUS_MODES = {"bugs", "security", "style", "all"}

_LANG_EXTENSIONS = {
    'python': ['.py'],
    'javascript': ['.js', '.jsx', '.mjs', '.cjs'],
    'typescript': ['.ts', '.tsx'],
    'go': ['.go'],
    'java': ['.java'],
    'ruby': ['.rb'],
    'rust': ['.rs'],
    'cpp': ['.cpp', '.cc', '.cxx', '.h', '.hpp'],
    'c': ['.c', '.h'],
    'php': ['.php'],
    'swift': ['.swift'],
    'kotlin': ['.kt'],
}


@dataclass
class ReviewConfig:
    enabled: bool = True
    focus: str = "all"
    ignore_paths: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    max_comments: int = 20

    @classmethod
    def from_dict(cls, data: dict) -> "ReviewConfig":
        focus = str(data.get('focus', 'all')).lower()
        if focus not in FOCUS_MODES:
            focus = 'all'
        return cls(
            enabled=bool(data.get('enabled', True)),
            focus=focus,
            ignore_paths=[str(p) for p in data.get('ignore_paths', [])],
            languages=[str(lang).lower() for lang in data.get('languages', [])],
            max_comments=int(data.get('max_comments', 20)),
        )

    def should_review_file(self, path: str) -> bool:
        for pattern in self.ignore_paths:
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(os.path.basename(path), pattern):
                return False
        if self.languages:
            allowed_exts: set = set()
            for lang in self.languages:
                allowed_exts.update(_LANG_EXTENSIONS.get(lang, [f'.{lang}']))
            _, ext = os.path.splitext(path)
            if ext.lower() not in allowed_exts:
                return False
        return True

    def focus_instruction(self) -> str:
        """Return an extra sentence for the LLM system prompt based on focus mode."""
        if self.focus == 'bugs':
            return " Focus only on likely bugs, logic errors, and crashes — skip style."
        if self.focus == 'security':
            return " Focus only on security vulnerabilities (injection, auth, data exposure, etc.)."
        if self.focus == 'style':
            return " Focus only on code style, naming, and readability — skip logic issues."
        return ""
