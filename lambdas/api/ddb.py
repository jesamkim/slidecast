from typing import Optional
import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

import deck_model as dm


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
        items = []
        kwargs = {
            "IndexName": "byUpdatedAt",
            "KeyConditionExpression": Key("status").eq(status),
            "ScanIndexForward": False,
        }
        while True:
            resp = self._table.query(**kwargs)
            items.extend(resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
        return items

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
        items = []
        kwargs = {"FilterExpression": Attr("type").eq("group")}
        while True:
            resp = self._table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
        return items

    def reserve_alias(self, alias: str, deck_id: str, now_iso: str) -> bool:
        """Atomic uniqueness gate: conditional PutItem of the ALIAS#{alias}
        reservation. Returns True if this call won the reservation, False
        if the alias is already reserved.
        """
        item = dm.new_alias_reservation(alias, deck_id, now_iso)
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(deckId)",
            )
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise

    def release_alias(self, alias: str) -> None:
        """Idempotent release of an alias reservation."""
        self._table.delete_item(Key={"deckId": dm.alias_pk(alias)})
