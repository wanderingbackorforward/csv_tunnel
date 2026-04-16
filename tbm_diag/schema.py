"""
schema.py — 字段别名映射、规范列名、单位定义

规则：
- 所有字段映射在此模块集中定义，其他模块不得硬编码中文列名
- 单位可疑的字段以 raw_ 前缀标记，不参与后续物理量计算
- FIELD_CATALOG 是唯一数据源，其他视图（RAW_TO_CANONICAL 等）均由它派生
"""

from __future__ import annotations

from dataclasses import dataclass

# ── 时间戳列常量 ────────────────────────────────────────────────────────────────
TIMESTAMP_RAW = "日期时间"
TIMESTAMP_CANONICAL = "timestamp"


# ── 字段元数据 ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FieldMeta:
    canonical: str        # 内部标准字段名（snake_case，ASCII）
    raw_unit: str         # 原始单位字符串（来自列名括号内）
    description_zh: str   # 中文描述
    suspicious_unit: bool = False   # True = 单位存疑，保留但不参与物理计算
    is_timestamp: bool = False      # True = 时间戳列，不做数值转换


# ── 主映射表：原始中文列名 → FieldMeta ─────────────────────────────────────────
#
# 字段顺序与 CSV 导出顺序一致，便于核对。
#
# ⚠️  "顶部左/右稳定器油缸行程(bar)" 两列：
#     列名表明是"行程"（stroke，通常单位为 mm），但括号内单位写的是 bar（压力单位）。
#     第一版保留原始值，映射到 raw_ 前缀字段，suspicious_unit=True，不参与任何物理量计算。
#     待现场工程师确认实际含义后再修正。
#
FIELD_CATALOG: dict[str, FieldMeta] = {
    # ── 基础参数 ─────────────────────────────────────────────────────────────────
    "日期时间": FieldMeta(
        canonical="timestamp",
        raw_unit="",
        description_zh="时间戳",
        is_timestamp=True,
    ),
    "环片计数器()": FieldMeta(
        canonical="ring_counter",
        raw_unit="",
        description_zh="环片计数器",
    ),
    # ── 盾体姿态 ─────────────────────────────────────────────────────────────────
    "前盾体倾角(%)": FieldMeta(
        canonical="front_shield_inclination_pct",
        raw_unit="%",
        description_zh="前盾体倾角",
    ),
    "前盾体翻转角(mm)": FieldMeta(
        canonical="front_shield_roll_mm",
        raw_unit="mm",
        description_zh="前盾体翻转角",
    ),
    "撑紧盾倾角(%)": FieldMeta(
        canonical="gripper_shield_inclination_pct",
        raw_unit="%",
        description_zh="撑紧盾倾角",
    ),
    "撑紧盾翻转角(mm)": FieldMeta(
        canonical="gripper_shield_roll_mm",
        raw_unit="mm",
        description_zh="撑紧盾翻转角",
    ),
    # ── 刀盘 ─────────────────────────────────────────────────────────────────────
    "刀盘速度(rpm)": FieldMeta(
        canonical="cutter_speed_rpm",
        raw_unit="rpm",
        description_zh="刀盘转速",
    ),
    "刀盘转矩(kNm)": FieldMeta(
        canonical="cutter_torque_kNm",
        raw_unit="kNm",
        description_zh="刀盘转矩",
    ),
    # ── 推进系统 ─────────────────────────────────────────────────────────────────
    "总推进力(KN)": FieldMeta(
        canonical="total_thrust_kN",
        raw_unit="kN",
        description_zh="总推进力",
    ),
    "贯入度(mm/r)": FieldMeta(
        canonical="penetration_rate_mm_per_rev",
        raw_unit="mm/r",
        description_zh="贯入度",
    ),
    "推进速度平均值(mm/min)": FieldMeta(
        canonical="advance_speed_mm_per_min",
        raw_unit="mm/min",
        description_zh="推进速度平均值",
    ),
    # ── 主推进液压压力 ────────────────────────────────────────────────────────────
    "主推进泵出口压力(bar)": FieldMeta(
        canonical="main_pump_pressure_bar",
        raw_unit="bar",
        description_zh="主推进泵出口压力",
    ),
    "主推系统控制油压力(bar)": FieldMeta(
        canonical="main_push_ctrl_pressure_bar",
        raw_unit="bar",
        description_zh="主推系统控制油压力",
    ),
    # ── 各组油缸推进压力 ──────────────────────────────────────────────────────────
    "A组油缸主推进压力(bar)": FieldMeta(
        canonical="thrust_cyl_A_pressure_bar",
        raw_unit="bar",
        description_zh="A组油缸主推进压力",
    ),
    "B组油缸主推进压力(bar)": FieldMeta(
        canonical="thrust_cyl_B_pressure_bar",
        raw_unit="bar",
        description_zh="B组油缸主推进压力",
    ),
    "C组油缸主推进压力(bar)": FieldMeta(
        canonical="thrust_cyl_C_pressure_bar",
        raw_unit="bar",
        description_zh="C组油缸主推进压力",
    ),
    "D组油缸主推进压力(bar)": FieldMeta(
        canonical="thrust_cyl_D_pressure_bar",
        raw_unit="bar",
        description_zh="D组油缸主推进压力",
    ),
    "E组油缸主推进压力(bar)": FieldMeta(
        canonical="thrust_cyl_E_pressure_bar",
        raw_unit="bar",
        description_zh="E组油缸主推进压力",
    ),
    "F组油缸主推进压力(bar)": FieldMeta(
        canonical="thrust_cyl_F_pressure_bar",
        raw_unit="bar",
        description_zh="F组油缸主推进压力",
    ),
    # ── 各组油缸推进行程 ──────────────────────────────────────────────────────────
    "A组主推进油缸行程(mm)": FieldMeta(
        canonical="thrust_cyl_A_stroke_mm",
        raw_unit="mm",
        description_zh="A组主推进油缸行程",
    ),
    "B组主推进油缸行程(mm)": FieldMeta(
        canonical="thrust_cyl_B_stroke_mm",
        raw_unit="mm",
        description_zh="B组主推进油缸行程",
    ),
    "C组主推进油缸行程(mm)": FieldMeta(
        canonical="thrust_cyl_C_stroke_mm",
        raw_unit="mm",
        description_zh="C组主推进油缸行程",
    ),
    "D组主推进油缸行程(mm)": FieldMeta(
        canonical="thrust_cyl_D_stroke_mm",
        raw_unit="mm",
        description_zh="D组主推进油缸行程",
    ),
    "E组主推进油缸行程(mm)": FieldMeta(
        canonical="thrust_cyl_E_stroke_mm",
        raw_unit="mm",
        description_zh="E组主推进油缸行程",
    ),
    "F组主推进油缸行程(mm)": FieldMeta(
        canonical="thrust_cyl_F_stroke_mm",
        raw_unit="mm",
        description_zh="F组主推进油缸行程",
    ),
    # ── 顶部稳定器 ───────────────────────────────────────────────────────────────
    "顶部左稳定器油缸无杆腔压力(bar)": FieldMeta(
        canonical="top_left_stab_rodless_pressure_bar",
        raw_unit="bar",
        description_zh="顶部左稳定器油缸无杆腔压力",
    ),
    "顶部右稳定器油缸无杆腔压力(bar)": FieldMeta(
        canonical="top_right_stab_rodless_pressure_bar",
        raw_unit="bar",
        description_zh="顶部右稳定器油缸无杆腔压力",
    ),
    # ⚠️ 以下两列：列名为"行程"但单位标注为 bar，物理意义存疑
    # 映射到 raw_ 前缀字段保留，不参与后续物理量计算，等待工程师确认
    "顶部左稳定器油缸行程(bar)": FieldMeta(
        canonical="raw_top_left_stab_stroke_bar",
        raw_unit="bar",          # 疑似应为 mm（行程），待现场确认
        description_zh="顶部左稳定器油缸行程（单位可疑，保留原始值）",
        suspicious_unit=True,
    ),
    "顶部右稳定器油缸行程(bar)": FieldMeta(
        canonical="raw_top_right_stab_stroke_bar",
        raw_unit="bar",          # 疑似应为 mm（行程），待现场确认
        description_zh="顶部右稳定器油缸行程（单位可疑，保留原始值）",
        suspicious_unit=True,
    ),
    # ── 前盾扭矩油缸 ─────────────────────────────────────────────────────────────
    "前盾1#和3#扭矩油缸无杆腔压力(bar)": FieldMeta(
        canonical="front_torque_cyl_13_pressure_bar",
        raw_unit="bar",
        description_zh="前盾1#和3#扭矩油缸无杆腔压力",
    ),
    # 同一列的带空格变体（部分导出文件列名含多余空格）
    "前盾1#和3#扭矩油缸无杆腔压力 (bar)": FieldMeta(
        canonical="front_torque_cyl_13_pressure_bar",
        raw_unit="bar",
        description_zh="前盾1#和3#扭矩油缸无杆腔压力",
    ),
    "前盾2#和4#扭矩油缸无杆腔压力(bar)": FieldMeta(
        canonical="front_torque_cyl_24_pressure_bar",
        raw_unit="bar",
        description_zh="前盾2#和4#扭矩油缸无杆腔压力",
    ),
    "前盾1#扭矩油缸行程(mm)": FieldMeta(
        canonical="front_torque_cyl_1_stroke_mm",
        raw_unit="mm",
        description_zh="前盾1#扭矩油缸行程",
    ),
    "前盾2#扭矩油缸行程(mm)": FieldMeta(
        canonical="front_torque_cyl_2_stroke_mm",
        raw_unit="mm",
        description_zh="前盾2#扭矩油缸行程",
    ),
    # ── 撑靴盾扭矩油缸 ───────────────────────────────────────────────────────────
    "撑靴盾5#和7#扭矩油缸无杆腔压力(bar)": FieldMeta(
        canonical="gripper_torque_cyl_57_pressure_bar",
        raw_unit="bar",
        description_zh="撑靴盾5#和7#扭矩油缸无杆腔压力",
    ),
    "撑靴盾6#和8#扭矩油缸无杆腔压力(bar)": FieldMeta(
        canonical="gripper_torque_cyl_68_pressure_bar",
        raw_unit="bar",
        description_zh="撑靴盾6#和8#扭矩油缸无杆腔压力",
    ),
    "撑靴盾1#扭矩油缸行程(mm)": FieldMeta(
        canonical="gripper_torque_cyl_1_stroke_mm",
        raw_unit="mm",
        description_zh="撑靴盾1#扭矩油缸行程",
    ),
    "撑靴盾2#扭矩油缸行程(mm)": FieldMeta(
        canonical="gripper_torque_cyl_2_stroke_mm",
        raw_unit="mm",
        description_zh="撑靴盾2#扭矩油缸行程",
    ),
    # ── 左右稳定器行程 ───────────────────────────────────────────────────────────
    "左稳定器油缸行程(mm)": FieldMeta(
        canonical="left_stabilizer_stroke_mm",
        raw_unit="mm",
        description_zh="左稳定器油缸行程",
    ),
    "右稳定器油缸行程(mm)": FieldMeta(
        canonical="right_stabilizer_stroke_mm",
        raw_unit="mm",
        description_zh="右稳定器油缸行程",
    ),
}

# ── 派生视图（只读，由 FIELD_CATALOG 生成，勿手动修改）────────────────────────

# 原始列名 → 标准列名
RAW_TO_CANONICAL: dict[str, str] = {
    raw: meta.canonical for raw, meta in FIELD_CATALOG.items()
}

# 标准列名 → FieldMeta
CANONICAL_META: dict[str, FieldMeta] = {
    meta.canonical: meta for meta in FIELD_CATALOG.values()
}

# 单位可疑字段集合（标准名）
SUSPICIOUS_UNIT_FIELDS: frozenset[str] = frozenset(
    meta.canonical for meta in FIELD_CATALOG.values() if meta.suspicious_unit
)

# 时间戳字段集合（标准名）
TIMESTAMP_FIELDS: frozenset[str] = frozenset(
    meta.canonical for meta in FIELD_CATALOG.values() if meta.is_timestamp
)


# ── 公开工具函数 ────────────────────────────────────────────────────────────────

def resolve_columns(
    raw_columns: list[str],
) -> tuple[dict[str, str], list[str]]:
    """
    将 CSV 原始列名列表解析为识别列映射和未识别列列表。

    Args:
        raw_columns: CSV 的原始列名列表（已 strip）

    Returns:
        recognized:   dict[原始列名 → 标准列名]，所有在 FIELD_CATALOG 中定义的列
        unrecognized: list[原始列名]，未在 FIELD_CATALOG 中定义的列（保留在 DataFrame 中）
    """
    recognized: dict[str, str] = {}
    unrecognized: list[str] = []

    for col in raw_columns:
        if col in FIELD_CATALOG:
            recognized[col] = FIELD_CATALOG[col].canonical
        else:
            unrecognized.append(col)

    return recognized, unrecognized
