from typing import Optional
import boto3
from boto3.dynamodb.conditions import Key, Attr


class DeckRepo:
    def __init__(self, table_name: str, dynamodb_resource=None):
        res = dynamodb_resource or boto3.resource("dynamodb")
        self._table = res.Table(table_name)

    def put(self, item: dict) -> None:
        clean = {k: v for k, v in item.items() if v is not None}
        self._table.put_item(Item=clean)

    def get(self, deck_id: str) -> Optional[dict]:
        resp = self._table.get_item(Key={"deckId": deck_id})
        return resp.get("Item")

    def list_by_status(self, status: str) -> list:
        resp = self._table.query(
            IndexName="byUpdatedAt",
            KeyConditionExpression=Key("status").eq(status),
            ScanIndexForward=False,
        )
        return resp.get("Items", [])

    def delete(self, deck_id: str) -> None:
        self._table.delete_item(Key={"deckId": deck_id})

    def query_by_alias(self, alias: str):
        resp = self._table.query(
            IndexName="byAlias",
            KeyConditionExpression=Key("alias").eq(alias),
        )
        items = resp.get("Items", [])
        return items[0] if items else None

    def list_groups(self) -> list:
        resp = self._table.scan(FilterExpression=Attr("type").eq("group"))
        return resp.get("Items", [])
