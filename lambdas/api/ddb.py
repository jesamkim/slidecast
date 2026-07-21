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

    def reserve_public(self, token: str, deck_id: str, public_version: int, now_iso: str) -> bool:
        """Atomic uniqueness gate: conditional PutItem of the PUBLIC#{token}
        reservation. Returns True if this call won the reservation, False if
        the token is already reserved.
        """
        item = dm.new_public_reservation(token, deck_id, public_version, now_iso)
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

    def release_public(self, token: str) -> None:
        """Idempotent release of a public token reservation."""
        self.delete(dm.public_pk(token))

    def increment_views(self, token: str, day: str) -> None:
        """Atomically bump total view count and the per-day bucket on the
        PUBLIC#{token} reservation item.

        This uses TWO UpdateItems on purpose. DynamoDB rejects `ADD` on a
        nested map path (e.g. `viewsByDay.#d`) when the parent map does not
        yet exist. So we:
          1) SET viewsByDay = if_not_exists(viewsByDay, :empty) and ADD to
             the top-level viewCount in one atomic call, ensuring the map
             exists after this step.
          2) ADD viewsByDay.#d :one now that the map is guaranteed present.
        Each call is atomic; both are monotonic increments, so total and
        per-day counters can never destructively diverge.
        """
        pk = dm.public_pk(token)
        self._table.update_item(
            Key={"deckId": pk},
            UpdateExpression=(
                "SET viewsByDay = if_not_exists(viewsByDay, :empty) "
                "ADD viewCount :one"
            ),
            ExpressionAttributeValues={":empty": {}, ":one": 1},
        )
        self._table.update_item(
            Key={"deckId": pk},
            UpdateExpression="ADD viewsByDay.#d :one",
            ExpressionAttributeNames={"#d": day},
            ExpressionAttributeValues={":one": 1},
        )

    def get_views(self, token: str) -> dict:
        """Read total and per-day view counts for a public token.
        Missing item/attributes yield total 0 and empty byDay.
        """
        item = self.get(dm.public_pk(token)) or {}
        raw = item.get("viewsByDay") or {}
        by_day = {k: int(v) for k, v in raw.items()}
        return {"total": int(item.get("viewCount", 0) or 0), "byDay": by_day}
