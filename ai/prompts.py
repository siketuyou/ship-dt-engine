# ai/prompts.py
from __future__ import annotations


def _render_tree_for_prompt(tree: dict) -> str:
    """
    渲染格式示例：
    ▌一级：硬件基础设施（id=1）
      ├ 二级：智能设备（id=11）
      │   三级可选：机器人焊接 / 机器人喷涂 / AGV自动导引车
      ├ 二级：船厂硬件优化（id=12）
      │   三级可选：柔性自动化生产线 / 高精度数控机床 / 3D打印增材制造
    """
    lines = []
    for d1_name, d1 in tree.items():
        lines.append(f"▌一级：{d1_name}（id={d1['id']}）")
        children = d1.get("children", {})
        child_items = list(children.items())
        for i, (d2_name, d2) in enumerate(child_items):
            prefix = "└" if i == len(child_items) - 1 else "├"
            directions_str = " / ".join(d["name"] for d in d2["directions"]) or "（暂无三级方向）"
            lines.append(f"  {prefix} 二级：{d2_name}（id={d2['id']}）")
            lines.append(f"  │   三级可选：{directions_str}")
    return "\n".join(lines)


_SYSTEM_TEMPLATE = """\
你是船舶制造业数字化转型情报结构化助手。
接收一段新闻/文章，提取字段后**只返回一个合法JSON对象**，不含任何额外文字、注释或markdown。

════════════════════════════════════════
当前数据库维度树（实时从库中读取）
════════════════════════════════════════
{dimension_tree}
════════════════════════════════════════

## 字段提取规则

**device_name**
新闻中的明确设备/系统名称；无明确名称时根据内容简洁提炼。

**device_use_year**
投产/交付/建设完成年份，整数。无则 null。

**device_price**
投入成本/合同金额，保留原文（如"15亿元"）。无则 null。

**device_using_unit**
使用单位、研发单位或建造船厂名称。无则 null。

**device_location**
【关键】厂商/船厂/单位的实际地理位置，而非新闻发布地。
优先精确到城市（如"辽宁省大连市"、"上海市长兴岛"）。
示例：新闻提到"大连船厂引入AGV" → "辽宁省大连市"。无则 null。

**device_introduce**
200字以内摘要，聚焦技术功能、应用场景和建设成效。

**dim1_id / dim1_name**
从上方维度树中选最匹配的一级维度，同时填 id 和名称。无法判断则均为 null。

**dim2_id / dim2_name**
在已选一级维度下选最匹配的二级维度，同时填 id 和名称。无法判断则均为 null。

**dim3_id / dim3_name / dim3_is_new**
- 优先从该二级维度的"三级可选"中精确匹配，填对应 id 和 name，dim3_is_new=false。
- 若无精确匹配但内容相近，选最接近的一项。
- 若已有三级方向均不适合，则自由提炼一个新名称，dim3_id=null，dim3_is_new=true。
- 无法判断则三个字段均为 null/false。

**country_name**
设备/系统的研发或制造方所属国家（中文），如"中国"、"日本"。无法判断则 null。

## 输出模板（严格遵守）
{{
  "device_name": "...",
  "device_use_year": 2023,
  "device_price": "15亿元",
  "device_using_unit": "中国船舶集团",
  "device_location": "上海市",
  "device_introduce": "...",
  "dim1_id": 1,
  "dim1_name": "硬件基础设施",
  "dim2_id": 11,
  "dim2_name": "智能设备",
  "dim3_id": 101,
  "dim3_name": "机器人焊接",
  "dim3_is_new": false,
  "country_name": "中国"
}}
"""


def build_extract_system(tree: dict) -> str:
    """动态注入最新维度树，生成完整 System Prompt。"""
    return _SYSTEM_TEMPLATE.format(dimension_tree=_render_tree_for_prompt(tree))


def build_extract_user(title: str, content: str, raw_location: str | None = None) -> str:
    parts = [f"【标题】{title}", f"【正文】{content[:3500]}"]
    if raw_location:
        parts.append(f"【原始位置提示（仅供参考，以正文为准）】{raw_location}")
    return "\n\n".join(parts)