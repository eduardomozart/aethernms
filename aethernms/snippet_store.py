"""XML snippet library management under hierarchical folders (e.g. snippets/aruba/aruba_procurve/)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import List, Optional
import xml.etree.ElementTree as ET

from aethernms.models import Snippet, SnippetSeverity, SnippetType
from aethernms.netmiko_catalog import normalize_legacy_platform
from aethernms.paths import (
    bundled_snippets_dir,
    get_snippets_dir,
    seed_bundled_templates,
)


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


def _parse_snippet_device_type(raw: Optional[str]) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        return "aruba_procurve"
    platform, _proto = normalize_legacy_platform(cleaned)
    return platform or cleaned


def snippet_to_xml_element(snippet: Snippet) -> ET.Element:
    """Convert a Snippet dataclass into an XML Element."""
    root = ET.Element("Snippet", version="1.0")
    ET.SubElement(root, "Name").text = snippet.name
    ET.SubElement(root, "Type").text = snippet.snippet_type.value
    ET.SubElement(root, "DeviceType").text = snippet.device_type or "aruba_procurve"
    ET.SubElement(root, "Severity").text = snippet.severity.value
    ET.SubElement(root, "Description").text = snippet.description or ""
    ET.SubElement(root, "CreatedAt").text = snippet.created_at or datetime.now().isoformat(
        timespec="seconds"
    )
    ET.SubElement(root, "Commands").text = snippet.commands or ""
    if snippet.audit_regex:
        ET.SubElement(root, "AuditRegex").text = snippet.audit_regex
    return root


def snippet_to_xml_string(snippet: Snippet) -> str:
    """Serialize a Snippet dataclass into a formatted UTF-8 XML document string."""
    root = snippet_to_xml_element(snippet)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ", level=0)
    xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
    return f'<?xml version="1.0" encoding="utf-8"?>\n{xml_str}\n'


def snippet_from_xml_element(
    root: ET.Element,
    default_name: str = "snippet",
    rel_folder: str = "",
    file_path: Optional[str] = None,
) -> Snippet:
    """Parse a <Snippet> XML Element into a Snippet instance."""
    if root.tag != "Snippet":
        raise ValueError(f"Expected <Snippet> root tag, found <{root.tag}>.")

    def _text(tag: str, default: str = "") -> str:
        el = root.find(tag)
        if el is not None and el.text is not None:
            return el.text
        return default

    device_type = _parse_snippet_device_type(_text("DeviceType"))
    folder = rel_folder or SnippetStore.default_folder_for_os(device_type)

    return Snippet(
        name=_text("Name", default_name).strip() or default_name,
        folder=folder,
        snippet_type=_enum_from_value(SnippetType, _text("Type"), SnippetType.CONFIG),
        device_type=device_type,
        severity=_enum_from_value(SnippetSeverity, _text("Severity"), SnippetSeverity.INFO),
        description=_text("Description", "").strip(),
        commands=_text("Commands", "").strip("\r\n"),
        audit_regex=_text("AuditRegex", "").strip("\r\n"),
        created_at=_text("CreatedAt", "").strip(),
        file_path=file_path,
    )


def snippet_from_xml_string(xml_text: str, default_name: str = "snippet") -> Snippet:
    """Parse an XML string into a Snippet instance."""
    root = ET.fromstring(xml_text)
    return snippet_from_xml_element(root, default_name=default_name)


def snippet_from_xml_file(xml_path: Path, base_dir: Optional[Path] = None) -> Snippet:
    """Parse an XML file into a Snippet instance."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    if root.tag != "Snippet":
        raise ValueError(f"Expected <Snippet> root tag in {xml_path}, found <{root.tag}>.")

    rel_folder = ""
    if base_dir is not None:
        try:
            rel_parent = xml_path.resolve().parent.relative_to(base_dir.resolve())
            rel_folder = normalize_folder_path(str(rel_parent))
        except ValueError:
            rel_folder = ""

    return snippet_from_xml_element(
        root,
        default_name=xml_path.stem,
        rel_folder=rel_folder,
        file_path=str(xml_path),
    )


class SnippetStore:
    """Manages hierarchical XML snippets under `snippets/` (e.g., snippets/aruba/aruba_procurve/)."""

    @staticmethod
    def default_folder_for_os(platform: str) -> str:
        """Return default relative subfolder following Netmiko <vendor>/<platform> convention."""
        val, _ = normalize_legacy_platform(platform)
        val = val or (platform or "").strip().lower()
        slug = slugify_filename(val)
        if not slug:
            return "generic"
        if "_" in slug:
            vendor, _rest = slug.split("_", 1)
            if vendor:
                return f"{vendor}/{slug}"
        return slug

    def __init__(self, base_dir: Optional[Path | str] = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else get_snippets_dir()

    def seed_defaults(self, source_dir: Optional[Path] = None) -> List[str]:
        """Seed bundled XML snippets into the target folder via SHA-256 tracking."""
        src = Path(source_dir) if source_dir else bundled_snippets_dir()
        try:
            return seed_bundled_templates(src, self.base_dir)
        except OSError:
            return []

    def ensure_default_folders(self) -> None:
        """Ensure standard snippet directories exist."""
        for rel in ("aruba/aruba_procurve", "aruba/aruba_aoscx"):
            try:
                (self.base_dir / rel).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

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

    def list_folders(self) -> List[str]:
        """Return sorted relative folder paths under snippets/."""
        if not self.base_dir.exists():
            return []
        folders: List[str] = []
        for p in self.base_dir.rglob("*"):
            if p.is_dir():
                rel = normalize_folder_path(str(p.relative_to(self.base_dir)))
                if rel:
                    folders.append(rel)
        return sorted(set(folders))

    def load_all_snippets(self) -> List[Snippet]:
        """Load every XML snippet recursively from snippets/."""
        if not self.base_dir.exists():
            return []
        snippets: List[Snippet] = []
        for xml_path in sorted(self.base_dir.rglob("*.xml")):
            try:
                snippets.append(snippet_from_xml_file(xml_path, base_dir=self.base_dir))
            except Exception:
                continue
        snippets.sort(key=lambda s: (s.folder.lower(), s.name.lower()))
        return snippets

    def save_snippet(self, snippet: Snippet, filename: Optional[str] = None) -> Path:
        """Persist a snippet as XML inside its designated subfolder under snippets/."""
        folder = normalize_folder_path(snippet.folder)
        if not folder:
            folder = self.default_folder_for_os(snippet.device_type)
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
            snippet.folder = self.default_folder_for_os(snippet.device_type)
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
