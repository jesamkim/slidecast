from typing import Optional
import boto3
from boto3.dynamodb.conditions import Key


class DeckRepo:
    def __init__(self, table_name: str, dynamodb_resource=None):
        res = dynamodb_resource or boto3.resource("dynamodb")
        self._table = res.Table(table_name)

    def put(self, item: dict) -> None:
        self._table.put_item(Item=item)

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
