"""XML device automation model storage under `model/<vendor>/<os>.xml`."""

from __future__ import annotations

from pathlib import Path
import re
from typing import List, Optional
import xml.etree.ElementTree as ET

from pssh_ui.models import DeviceModel, SwitchOS, parse_device_type
from pssh_ui.paths import (
    bundled_models_dir,
    get_models_dir,
    is_frozen,
    seed_bundled_templates,
)


DEFAULT_MODELS_DIR = get_models_dir()


def _normalize_folder(folder: str) -> str:
    cleaned = (folder or "").replace("\\", "/").strip("/")
    parts = [p for p in cleaned.split("/") if p and p not in (".", "..")]
    return "/".join(parts) or "custom"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "model").strip()).strip("._")
    return (slug or "model").lower()


def _enum_os(raw: str | None) -> SwitchOS | str:
    return parse_device_type(raw, SwitchOS.UNKNOWN)


def model_to_xml_element(model: DeviceModel) -> ET.Element:
    """Serialize a DeviceModel into XML."""
    root = ET.Element("DeviceModel", version="1.0")
    ET.SubElement(root, "Name").text = model.name
    ET.SubElement(root, "DeviceType").text = model.device_type.value
    ET.SubElement(root, "Vendor").text = model.vendor or "Aruba"
    ET.SubElement(root, "Description").text = model.description or ""
    ET.SubElement(root, "CliPromptRegex").text = model.cli_prompt_regex or ""
    ET.SubElement(root, "UsernamePromptRegex").text = model.username_prompt_regex or ""
    ET.SubElement(root, "PasswordPromptRegex").text = model.password_prompt_regex or ""
    ET.SubElement(root, "EnableCommand").text = model.enable_command or ""
    ET.SubElement(root, "EnablePromptRegex").text = model.enable_prompt_regex or ""
    ET.SubElement(root, "EnablePasswordPromptRegex").text = model.enable_password_prompt_regex or ""
    ET.SubElement(root, "PagerPromptRegex").text = model.pager_prompt_regex or ""
    ET.SubElement(root, "PagerDismissKey").text = model.pager_dismiss_key if model.pager_dismiss_key is not None else " "
    ET.SubElement(root, "DisablePagingCommand").text = model.disable_paging_command or ""
    ET.SubElement(root, "PreConfigCommands").text = model.pre_config_commands or ""
    ET.SubElement(root, "PostConfigCommands").text = model.post_config_commands or ""
    ET.SubElement(root, "WriteCommand").text = model.write_command or ""
    ET.SubElement(root, "PreAuditCommands").text = model.pre_audit_commands or ""
    ET.SubElement(root, "PostAuditCommands").text = model.post_audit_commands or ""
    return root


def model_from_xml_file(xml_path: Path, base_dir: Optional[Path] = None) -> DeviceModel:
    """Parse a DeviceModel XML file."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    if root.tag != "DeviceModel":
        raise ValueError(f"Expected <DeviceModel> root tag in {xml_path}, found <{root.tag}>.")

    def _txt(tag: str, default: str = "") -> str:
        el = root.find(tag)
        return el.text if (el is not None and el.text is not None) else default

    rel_folder = ""
    if base_dir is not None:
        try:
            rel_parent = xml_path.resolve().parent.relative_to(base_dir.resolve())
            rel_folder = _normalize_folder(str(rel_parent))
        except ValueError:
            rel_folder = ""

    vendor = _txt("Vendor", "Aruba").strip() or "Aruba"
    return DeviceModel(
        name=_txt("Name", xml_path.stem).strip() or xml_path.stem,
        device_type=_enum_os(_txt("DeviceType", SwitchOS.AOS_S.value)),
        vendor=vendor,
        folder=rel_folder or _normalize_folder(vendor.lower()),
        description=_txt("Description", "").strip(),
        cli_prompt_regex=_txt(
            "CliPromptRegex",
            r"(?:^|\n)[ \t]*[A-Za-z0-9_.:-]+(?:\([^)\r\n]+\))?[#>][ \t]*$",
        ),
        username_prompt_regex=_txt("UsernamePromptRegex", r"(?:Username|Login|User)\s*:"),
        password_prompt_regex=_txt(
            "PasswordPromptRegex", r"(?:Enable\s+password|Password)\s*:"
        ),
        enable_command=_txt("EnableCommand", "enable").strip(),
        enable_prompt_regex=_txt(
            "EnablePromptRegex",
            r"(?:^|\n)[ \t]*[A-Za-z0-9_.:-]+(?:\([^)\r\n]+\))?#\s*$",
        ),
        enable_password_prompt_regex=_txt(
            "EnablePasswordPromptRegex", r"(?:Enable\s+password|Password)\s*:"
        ),
        pager_prompt_regex=_txt(
            "PagerPromptRegex",
            r"(?:Press any key to continue|--\s*MORE\s*--|Press <SPACE> to continue)",
        ),
        pager_dismiss_key=_txt("PagerDismissKey", " "),
        disable_paging_command=_txt("DisablePagingCommand", "no page").strip(),
        pre_config_commands=_txt("PreConfigCommands", "configure terminal").strip("\r\n"),
        post_config_commands=_txt("PostConfigCommands", "end").strip("\r\n"),
        write_command=_txt("WriteCommand", "").strip(),
        pre_audit_commands=_txt("PreAuditCommands", "").strip("\r\n"),
        post_audit_commands=_txt("PostAuditCommands", "").strip("\r\n"),
        file_path=str(xml_path),
    )


class ModelStore:
    """Manages reusable XML device automation models under `model/`."""

    def __init__(self, base_dir: Optional[Path | str] = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else get_models_dir()

    def seed_defaults(self, source_dir: Optional[Path] = None) -> List[str]:
        """Seed bundled XML device models into user folder when frozen (or explicit source_dir)."""
        if source_dir is None and not is_frozen():
            return []
        src = Path(source_dir) if source_dir else bundled_models_dir()
        return seed_bundled_templates(src, self.base_dir)

    def load_all_models(self) -> List[DeviceModel]:
        """Recursively load all DeviceModel XML definitions from `model/`."""
        if not self.base_dir.exists():
            return []
        models: List[DeviceModel] = []
        for xml_path in sorted(self.base_dir.rglob("*.xml")):
            try:
                models.append(model_from_xml_file(xml_path, base_dir=self.base_dir))
            except Exception:
                continue
        models.sort(key=lambda m: (m.device_type.value.lower(), m.name.lower()))
        return models

    @staticmethod
    def _write_model_xml(model: DeviceModel, out_path: Path) -> None:
        root = model_to_xml_element(model)
        tree = ET.ElementTree(root)
        ET.indent(tree, space="    ", level=0)
        xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
        with out_path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write('<?xml version="1.0" encoding="utf-8"?>\n')
            fh.write(xml_str)
            fh.write("\n")

    def save_model(self, model: DeviceModel, filename: Optional[str] = None) -> Path:
        """Persist a DeviceModel XML file under `model/<folder>/`."""
        folder = _normalize_folder(model.folder or (model.vendor or "custom").lower())
        target_dir = (self.base_dir / folder).resolve()
        base_resolved = self.base_dir.resolve()
        if base_resolved != target_dir and base_resolved not in target_dir.parents:
            raise ValueError(f"Invalid folder path outside model directory: {folder}")
        target_dir.mkdir(parents=True, exist_ok=True)

        if filename:
            out_name = f"{_slugify(Path(filename).stem)}.xml"
        elif model.file_path and Path(model.file_path).parent.resolve() == target_dir:
            out_name = Path(model.file_path).name
        else:
            out_name = f"{_slugify(model.name)}.xml"

        out_path = target_dir / out_name
        self._write_model_xml(model, out_path)
        model.file_path = str(out_path)
        return out_path

    def export_model(self, model: DeviceModel, destination: Path | str) -> Path:
        """Export a DeviceModel XML file to an arbitrary destination path."""
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._write_model_xml(model, dest)
        return dest

    def import_model(
        self,
        source_path: Path | str,
        target_folder: Optional[str] = None,
    ) -> DeviceModel:
        """Import an external DeviceModel XML file into `model/<vendor>/`."""
        src = Path(source_path)
        model = model_from_xml_file(src, base_dir=None)
        if target_folder is not None and _normalize_folder(target_folder):
            model.folder = _normalize_folder(target_folder)
        elif not model.folder:
            model.folder = _normalize_folder((model.vendor or "custom").lower())
        model.file_path = None
        self.save_model(model, filename=src.name)
        return model

    def delete_model(self, model: DeviceModel) -> bool:
        """Delete a DeviceModel XML file from disk."""
        if not model.file_path:
            return False
        target = Path(model.file_path).resolve()
        base_resolved = self.base_dir.resolve()
        if base_resolved not in target.parents:
            raise ValueError("Refusing to delete file outside model directory.")
        if target.is_file():
            target.unlink()
            return True
        return False

    @staticmethod
    def get_model_for_os(
        os_type: SwitchOS, models: List[DeviceModel], preferred_name: str = ""
    ) -> Optional[DeviceModel]:
        """Return matching DeviceModel by name/OS, or None if unavailable."""
        if preferred_name:
            by_name = next((m for m in models if m.name == preferred_name), None)
            if by_name:
                return by_name
        return next((m for m in models if m.device_type == os_type), None)
