from db_core import add_event_log, get_entity_facts, search_event_log, upsert_entity_fact

print("--- MASE 2.0 白盒记忆引擎测试 ---")

# 1. 模拟 Notetaker (记事智能体) 写入时间线冲突的对话日志
print("1. 写入带有时间冲突的对话...")
add_event_log("thread_001", "user", "我的项目预算是 500 美元")
add_event_log("thread_002", "user", "不对，那个项目的预算追加到了 1000 美元")
add_event_log("thread_003", "user", "今天天气真不错，我和 Alice 去打了网球")

# 2. 模拟 Notetaker 从对话中提取出了核心“实体状态”，进行 Upsert 归档
print("2. 从对话中提取出结构化事实，更新实体档案...")
upsert_entity_fact("finance_budget", "project_budget", "$500")
print("  -> 事实入库：预算=$500")
# 第二天：预算变更了！Notetaker 会自动覆盖它
upsert_entity_fact("finance_budget", "project_budget", "$1000")
print("  -> 事实更新：预算=$1000 (旧数据已被覆盖)")

upsert_entity_fact("location_events", "recent_sport_partner", "Alice, Tennis")

# 3. 模拟 Executor 回答复杂问题：“我的项目预算现在是多少？”
print("\n--- 开始检索测试 ---")

# a) 查阅底层流水账 (Event Log) 演示 BM25 算法的效果
print("\n[BM25] 如果去查底层的流水账:")
results = search_event_log(["预算"])
for res in results:
    # rank 越低（负数）越好
    print(f"  [得分: {res['score']}] 日志: {res['content']}")
print("  (问题出现：旧的 500 美元也会被搜出来，小模型很容易阅读理解失败！)")

# b) 查阅顶层实体档案 (Entity Fact Sheet) 演示降维打击
print("\n[Upsert] 如果去查实体档案表:")
facts = get_entity_facts(category="finance_budget")
for fact in facts:
    print(f"  属性: {fact['entity_key']} => 最新值: {fact['entity_value']} (更新于 {fact['updated_at']})")
print("  (降维打击：模型拿到的永远是最新的状态 1000 美元，没有任何干扰项！)")

