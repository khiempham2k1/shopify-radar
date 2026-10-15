"""Impact areas (config/impact_areas.txt): the fixed list Claude picks from.

Each line is `id | group | label | description`. The group says who is
affected (theme, partner, merchant) or `none` for items that do not matter to
a theme business; those are hidden but stay reachable, with Claude's reason.
"""

from __future__ import annotations

from dataclasses import dataclass

GROUPS = ("theme", "partner", "merchant", "none")


@dataclass(frozen=True)
class Area:
    id: str
    group: str
    label: str
    description: str

    @property
    def relevant(self) -> bool:
        return self.group != "none"


def parse_areas(text: str) -> list[Area]:
    areas: list[Area] = []
    seen: set[str] = set()
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4 or not all(parts):
            raise ValueError(f"Dòng {number}: cần đúng 4 phần 'id | nhóm | tên | mô tả'")
        area_id, group, label, description = parts
        if group not in GROUPS:
            raise ValueError(f"Dòng {number}: nhóm phải là một trong {', '.join(GROUPS)}")
        if area_id in seen:
            raise ValueError(f"Dòng {number}: id '{area_id}' bị trùng")
        seen.add(area_id)
        areas.append(Area(area_id, group, label, description))
    if not any(a.relevant for a in areas) or not any(not a.relevant for a in areas):
        raise ValueError("Cần ít nhất một mảng liên quan và một mảng nhóm none")
    return areas


def render_areas(areas: list[Area]) -> str:
    names = {"theme": "Theme (code)", "partner": "Partner (bán theme)", "merchant": "Merchant (dùng theme)", "none": "KHÔNG liên quan"}
    blocks = []
    for group in GROUPS:
        rows = [f"- {a.id}: {a.label} — {a.description}" for a in areas if a.group == group]
        if rows:
            blocks.append(f"{names[group]}:\n" + "\n".join(rows))
    return "\n\n".join(blocks)
