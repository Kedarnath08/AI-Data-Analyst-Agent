"""Schema-introspection tools exposed to the agent."""
from src.analyst import duck


def list_tables_tool(dataset_id: str) -> dict:
    return {"tables": duck.list_tables(dataset_id)}


def get_schema_tool(dataset_id: str, table: str | None = None) -> dict:
    schema = duck.get_schema(dataset_id)
    if table:
        if table not in schema:
            return {"error": f"Table '{table}' not found.",
                    "available_tables": list(schema.keys())}
        return {"table": table, "columns": schema[table]}
    return {"schema": schema}
