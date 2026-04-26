"""生成 3 类边界测试 CSV"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
from pathlib import Path

Path("incoming").mkdir(exist_ok=True)

base_ts = pd.date_range("2025-03-01 08:00:00", periods=300, freq="1s")

def base_row(ts, speed=25.0, torque=800.0, thrust=3000.0, pen=3.0):
    return {
        "日期时间": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "环片计数器()": 42,
        "前盾体倾角(%)": 0.1,
        "前盾体翻转角(mm)": 2.0,
        "撑紧盾倾角(%)": 0.1,
        "撑紧盾翻转角(mm)": 2.0,
        "刀盘速度(rpm)": 2.5,
        "刀盘转矩(kNm)": torque,
        "总推进力(KN)": thrust,
        "贯入度(mm/r)": pen,
        "推进速度平均值(mm/min)": speed,
        "主推进泵出口压力(bar)": 80.0,
        "主推系统控制油压力(bar)": 30.0,
        "A组油缸主推进压力(bar)": 120.0,
        "B组油缸主推进压力(bar)": 121.0,
        "C组油缸主推进压力(bar)": 119.0,
        "D组油缸主推进压力(bar)": 120.0,
        "E组油缸主推进压力(bar)": 122.0,
        "F组油缸主推进压力(bar)": 120.0,
        "A组主推进油缸行程(mm)": 500.0,
        "B组主推进油缸行程(mm)": 501.0,
        "C组主推进油缸行程(mm)": 499.0,
        "D组主推进油缸行程(mm)": 500.0,
        "E组主推进油缸行程(mm)": 502.0,
        "F组主推进油缸行程(mm)": 500.0,
        "顶部左稳定器油缸无杆腔压力(bar)": 50.0,
        "顶部右稳定器油缸无杆腔压力(bar)": 50.0,
        "顶部左稳定器油缸行程(bar)": 10.0,
        "顶部右稳定器油缸行程(bar)": 10.0,
        "前盾1#和3#扭矩油缸无杆腔压力(bar)": 40.0,
        "前盾2#和4#扭矩油缸无杆腔压力(bar)": 40.0,
        "撑靴盾5#和7#扭矩油缸无杆腔压力(bar)": 40.0,
        "撑靴盾6#和8#扭矩油缸无杆腔压力(bar)": 40.0,
        "前盾1#扭矩油缸行程(mm)": 100.0,
        "前盾2#扭矩油缸行程(mm)": 100.0,
        "撑靴盾1#扭矩油缸行程(mm)": 100.0,
        "撑靴盾2#扭矩油缸行程(mm)": 100.0,
        "左稳定器油缸行程(mm)": 200.0,
        "右稳定器油缸行程(mm)": 200.0,
    }

# A. 正常掘进段
rows = [base_row(ts) for ts in base_ts]
pd.DataFrame(rows).to_csv("incoming/normal_segment.csv", index=False, encoding="utf-8-sig")
print("OK normal_segment.csv (300 rows, steady excavation)")

# B. 明显异常段（转矩高 + 速度低 + 贯入度低）
rows = []
for i, ts in enumerate(base_ts):
    if 50 <= i < 200:
        rows.append(base_row(ts, speed=2.0, torque=3500.0, thrust=5000.0, pen=0.3))
    else:
        rows.append(base_row(ts))
pd.DataFrame(rows).to_csv("incoming/anomaly_segment.csv", index=False, encoding="utf-8-sig")
print("OK anomaly_segment.csv (150s high-torque low-speed anomaly)")

# C. 边界情况：缺列 + 重复时间戳 + 脏值 + 短时尖峰
rows = []
for i, ts in enumerate(base_ts):
    r = base_row(ts)
    if 10 <= i < 13:
        r["刀盘转矩(kNm)"] = 99999.0   # 短时尖峰
    if 30 <= i < 35:
        r["推进速度平均值(mm/min)"] = float("nan")  # 脏值
    rows.append(r)

df = pd.DataFrame(rows)
df = df.drop(columns=["贯入度(mm/r)", "主推系统控制油压力(bar)", "撑靴盾1#扭矩油缸行程(mm)"])
df.iloc[51, df.columns.get_loc("日期时间")] = df.iloc[50]["日期时间"]  # 重复时间戳
df.iloc[100, df.columns.get_loc("日期时间")] = "2025/03/01 08:01:40"  # 不同时间格式
df.to_csv("incoming/edge_cases.csv", index=False, encoding="utf-8-sig")
print("OK edge_cases.csv (missing cols, dup timestamps, NaN, spike, mixed time format)")

# D. 故意损坏的文件
with open("incoming/broken_file.csv", "w", encoding="utf-8") as f:
    f.write("this,is,not,valid,tbm,data\n")
    f.write("garbage,,,,,\n")
    f.write("1,2,3,4,5,6\n")
print("OK broken_file.csv (garbage content)")
