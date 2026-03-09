from neo4j import GraphDatabase

d = GraphDatabase.driver(
    "neo4j+ssc://715af161.databases.neo4j.io",
    auth=("715af161", "bvLwa_AauMd-zWGLYrc6-QoIB8zYtFHipDa9464ni0s"),
)
s = d.session()

print("=== NODES ===")
for r in s.run("MATCH (n) RETURN labels(n)[0] AS label, n.id AS id, n.name AS name ORDER BY label, id").data():
    print(f"  [{r['label']}] {r['id']}: {r['name']}")

total_n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
print(f"\nTotal nodes: {total_n}")

print("\n=== RELATIONSHIPS ===")
for r in s.run("MATCH (a)-[r]->(b) RETURN type(r) AS rel, a.id AS from_id, b.id AS to_id ORDER BY rel, from_id").data():
    print(f"  {r['from_id']} -[{r['rel']}]-> {r['to_id']}")

total_r = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
print(f"\nTotal relationships: {total_r}")

s.close()
d.close()
