import sqlite3, sys
db = r"d:\藏数据\raw\agent\memory.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

indexes = conn.execute(
    "SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND tbl_name='agent_memory'"
).fetchall()
print("索引列表:")
for idx in indexes:
    print(f"  {idx['name']} on {idx['tbl_name']}")

print()
plan = conn.execute(
    "EXPLAIN QUERY PLAN SELECT * FROM agent_memory WHERE uid = ?", ("u001",)
).fetchall()
print("按 uid 查询计划:")
for row in plan:
    print(f"  {dict(row)}")

plan2 = conn.execute(
    "EXPLAIN QUERY PLAN SELECT * FROM agent_memory WHERE uid = ? AND action = ?", ("u001", "keep")
).fetchall()
print("\n按 uid+action 查询计划:")
for row in plan2:
    print(f"  {dict(row)}")

plan3 = conn.execute(
    "EXPLAIN QUERY PLAN SELECT * FROM agent_memory WHERE uid = ? AND memory_key = ?", ("u001", "output_style")
).fetchall()
print("\n按 uid+key 查询计划:")
for row in plan3:
    print(f"  {dict(row)}")

conn.close()
