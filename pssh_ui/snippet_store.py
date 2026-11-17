"""XML snippet library management under hierarchical folders (e.g. snippets/aruba/aoss/)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import List, Optional
import xml.etree.ElementTree as ET

from pssh_ui.models import Snippet, SnippetSeverity, SnippetType, SwitchOS, parse_device_type
from pssh_ui.paths import get_external_snippets_dir, get_snippets_dir


DEFAULT_SNIPPETS_DIR = get_snippets_dir()


def normalize_folder_path(folder: str) -> str:
    """Normalize a snippet folder path into a safe POSIX relative path."""
    cleaned = (folder or "").replace("\\", "/").strip("/")
    parts = [p for p in cleaned.split("/") if p and p not in (".", "..")]
    return "/".join(parts)


def slugify_filename(name: str) -> str:
    """Generate a safe lowercase XML filename stem from a snippet name."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "snippet").strip()).strip("._")
    return (slug or "snippet").lower()


def _enum_from_value(enum_cls, value: str, default):
    for member in enum_cls:
        if member.value.lower() == (value or "").strip().lower():
            return member
    return default


def snippet_to_xml_element(snippet: Snippet) -> ET.Element:
    """Convert a Snippet dataclass into an XML Element."""
    root = ET.Element("Snippet", version="1.0")
    ET.SubElement(root, "Name").text = snippet.name
    ET.SubElement(root, "Type").text = snippet.snippet_type.value
    ET.SubElement(root, "DeviceType").text = snippet.device_type.value
    ET.SubElement(root, "Severity").text = snippet.severity.value
    ET.SubElement(root, "Description").text = snippet.description or ""
    ET.SubElement(root, "CreatedAt").text = snippet.created_at or datetime.now().isoformat(
        timespec="seconds"
    )
    ET.SubElement(root, "Commands").text = snippet.commands or ""
    if snippet.audit_regex:
        ET.SubElement(root, "AuditRegex").text = snippet.audit_regex
    return root


def snippet_from_xml_file(xml_path: Path, base_dir: Optional[Path] = None) -> Snippet:
    """Parse an XML file into a Snippet instance."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    if root.tag != "Snippet":
        raise ValueError(f"Expected <Snippet> root tag in {xml_path}, found <{root.tag}>.")

    def _text(tag: str, default: str = "") -> str:
        el = root.find(tag)
        if el is not None and el.text is not None:
            return el.text
        return default

    rel_folder = ""
    if base_dir is not None:
        try:
            rel_parent = xml_path.resolve().parent.relative_to(base_dir.resolve())
            rel_folder = normalize_folder_path(str(rel_parent))
        except ValueError:
            rel_folder = ""

    device_type = parse_device_type(_text("DeviceType"), SwitchOS.UNKNOWN)
    folder = rel_folder or SnippetStore.default_folder_for_os(device_type)

    return Snippet(
        name=_text("Name", xml_path.stem).strip() or xml_path.stem,
        folder=folder,
        snippet_type=_enum_from_value(SnippetType, _text("Type"), SnippetType.CONFIG),
        device_type=device_type,
        severity=_enum_from_value(SnippetSeverity, _text("Severity"), SnippetSeverity.INFO),
        description=_text("Description", "").strip(),
        commands=_text("Commands", "").strip("\r\n"),
        audit_regex=_text("AuditRegex", "").strip("\r\n"),
        created_at=_text("CreatedAt", "").strip(),
        file_path=str(xml_path),
    )


class SnippetStore:
    """Manages hierarchical XML snippets under `snippets/` (e.g., snippets/aruba/aoss/)."""

    @staticmethod
    def default_folder_for_os(os_type: SwitchOS | str) -> str:
        """Return default relative subfolder for a SwitchOS or dynamically discovered XML DeviceType."""
        val = os_type.value if hasattr(os_type, "value") else str(os_type or "")
        if val == SwitchOS.AOS_S.value:
            return "aruba/aoss"
        if val == SwitchOS.AOS_CX.value:
            return "aruba/aoscx"
        slug = slugify_filename(val)
        return f"custom/{slug}" if slug else "custom"

    def __init__(self, base_dir: Optional[Path | str] = None) -> None:
        self._explicit_base_dir = base_dir is not None
        self.base_dir = Path(base_dir) if base_dir else get_snippets_dir()

    def ensure_default_folders(self) -> None:
        """Ensure standard vendor/OS snippet directories exist."""
        for rel in ("aruba/aoss", "aruba/aoscx"):
            (self.base_dir / rel).mkdir(parents=True, exist_ok=True)

    def create_folder(self, relative_folder: str) -> Path:
        """Create a subfolder inside snippets/ safely."""
        norm = normalize_folder_path(relative_folder)
        if not norm:
            raise ValueError("Folder path cannot be empty.")
        target = (self.base_dir / norm).resolve()
        base_resolved = self.base_dir.resolve()
        if base_resolved != target and base_resolved not in target.parents:
            raise ValueError(f"Invalid folder path outside snippets directory: {relative_folder}")
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _search_roots(self) -> List[Path]:
        roots = [self.base_dir]
        if not self._explicit_base_dir:
            ext = get_external_snippets_dir()
            if ext and ext.is_dir() and ext.resolve() != self.base_dir.resolve():
                roots.append(ext)
        return roots

    def list_folders(self) -> List[str]:
        """Return sorted relative folder paths under snippets/."""
        folders: List[str] = []
        for root in self._search_roots():
            if not root.exists():
                continue
            for p in root.rglob("*"):
                if p.is_dir():
                    rel = normalize_folder_path(str(p.relative_to(root)))
                    if rel:
                        folders.append(rel)
        return sorted(set(folders))

    def load_all_snippets(self) -> List[Snippet]:
        """Load every XML snippet recursively from bundled and optional companion snippets/."""
        snippets: List[Snippet] = []
        for root in self._search_roots():
            if not root.exists():
                continue
            for xml_path in sorted(root.rglob("*.xml")):
                try:
                    snippets.append(snippet_from_xml_file(xml_path, base_dir=root))
                except Exception:
                    continue
        snippets.sort(key=lambda s: (s.folder.lower(), s.name.lower()))
        return snippets

    def save_snippet(self, snippet: Snippet, filename: Optional[str] = None) -> Path:
        """Persist a snippet as XML inside its designated subfolder under snippets/."""
        folder = normalize_folder_path(snippet.folder)
        if not folder:
            if snippet.device_type == SwitchOS.AOS_S:
                folder = "aruba/aoss"
            elif snippet.device_type == SwitchOS.AOS_CX:
                folder = "aruba/aoscx"
            else:
                folder = "custom"
            snippet.folder = folder

        target_dir = self.create_folder(folder)

        if filename:
            stem = Path(filename).stem
            out_name = f"{slugify_filename(stem)}.xml"
        elif snippet.file_path and Path(snippet.file_path).parent.resolve() == target_dir.resolve():
            out_name = Path(snippet.file_path).name
        else:
            out_name = f"{slugify_filename(snippet.name)}.xml"

        out_path = target_dir / out_name
        if not snippet.created_at:
            snippet.created_at = datetime.now().isoformat(timespec="seconds")

        self._write_snippet_xml(snippet, out_path)
        snippet.file_path = str(out_path)
        return out_path

    def export_snippet(self, snippet: Snippet, destination: Path | str) -> Path:
        """Export a snippet XML file to an arbitrary destination path."""
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._write_snippet_xml(snippet, dest)
        return dest

    def import_snippet(
        self,
        source_path: Path | str,
        target_folder: Optional[str] = None,
    ) -> Snippet:
        """Import an external XML snippet into snippets/<target_folder>/."""
        src = Path(source_path)
        snippet = snippet_from_xml_file(src, base_dir=None)
        if target_folder is not None and normalize_folder_path(target_folder):
            snippet.folder = normalize_folder_path(target_folder)
        elif not snippet.folder:
            if snippet.device_type == SwitchOS.AOS_S:
                snippet.folder = "aruba/aoss"
            elif snippet.device_type == SwitchOS.AOS_CX:
                snippet.folder = "aruba/aoscx"
            else:
                snippet.folder = "custom"
        snippet.file_path = None
        self.save_snippet(snippet, filename=src.name)
        return snippet

    def delete_snippet(self, snippet: Snippet) -> bool:
        """Delete a saved snippet file from disk."""
        if not snippet.file_path:
            return False
        target = Path(snippet.file_path).resolve()
        base_resolved = self.base_dir.resolve()
        if base_resolved not in target.parents:
            raise ValueError("Refusing to delete file outside snippets directory.")
        if target.is_file():
            target.unlink()
            return True
        return False

    @staticmethod
    def _write_snippet_xml(snippet: Snippet, out_path: Path) -> None:
        root = snippet_to_xml_element(snippet)
        tree = ET.ElementTree(root)
        ET.indent(tree, space="    ", level=0)
        xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
        with out_path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write('<?xml version="1.0" encoding="utf-8"?>\n')
            fh.write(xml_str)
            fh.write("\n")
