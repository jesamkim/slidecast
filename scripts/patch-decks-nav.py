#!/usr/bin/env python3
"""Retrofit already-uploaded slide decks with the Slidecast postMessage bridge.

Scans s3://<BucketName>/slides/*/v*/index.html, injects a small navigation
bridge shim in front of the html-slide engine's `fit(); show(cur);` call so
the deck can be driven by a parent viewer via postMessage.

Idempotent: files containing the marker `/* slidecast-nav bridge */` are
skipped. Files that do not contain the html-slide engine signature
`fit(); show(cur);` are logged as "unsupported" and left untouched.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


MARKER = "/* slidecast-nav bridge */"
ENGINE_SIGNATURE = "fit(); show(cur);"

SHIM = r"""/* slidecast-nav bridge */
(function(){
  if (window.parent === window) return;
  function bc(){ try { window.parent.postMessage({type:"slidecast-state",cur:(location.hash.slice(1)|0)||1,total:document.querySelectorAll('.slide').length}, "*"); } catch(e){} }
  addEventListener("message", function(e){
    var d=e.data; if(!d||d.type!=="slidecast-nav")return;
    if(d.action==="next") dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowRight"}));
    else if(d.action==="prev") dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowLeft"}));
    else if(d.action==="ping") bc();
  });
  addEventListener("hashchange", bc);
  try {
    new MutationObserver(bc).observe(
      document.getElementById('stage') || document.body,
      { subtree: true, attributes: true, attributeFilter: ['class'] }
    );
  } catch (e) {}
})();
"""


def read_bucket_name() -> str:
    outputs_path = Path(__file__).resolve().parent.parent / "cdk-outputs.json"
    with outputs_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    for stack_name, outputs in data.items():
        if "BucketName" in outputs:
            return outputs["BucketName"]
    raise RuntimeError("BucketName not found in cdk-outputs.json")


def build_patched(body: str) -> str:
    injection = SHIM + "      " + ENGINE_SIGNATURE
    return body.replace(ENGINE_SIGNATURE, injection, 1)


def is_valid_html(body: str) -> bool:
    return len(body) > 0 and "</html>" in body.lower()


def process(dry_run: bool) -> int:
    import boto3  # imported lazily so --help works without AWS deps

    bucket = read_bucket_name()
    session = boto3.Session(
        profile_name=os.environ.get("AWS_PROFILE", "profile2"),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )
    s3 = session.client("s3")

    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="slides/"):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            if key.endswith("/index.html"):
                keys.append(key)

    counts = {"patch": 0, "skip": 0, "unsupported": 0, "invalid": 0}
    for key in keys:
        head = s3.head_object(Bucket=bucket, Key=key)
        cache_control = head.get("CacheControl")
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8", errors="replace")

        if MARKER in body:
            counts["skip"] += 1
            print(f"skip-already-patched  {key}")
            continue

        if ENGINE_SIGNATURE not in body:
            counts["unsupported"] += 1
            print(f"unsupported           {key}")
            continue

        new_body = build_patched(body)
        if not is_valid_html(new_body):
            counts["invalid"] += 1
            print(f"invalid-skip          {key}")
            continue

        if dry_run:
            counts["patch"] += 1
            print(f"patch (dry-run)       {key}")
            continue

        put_kwargs = {
            "Bucket": bucket,
            "Key": key,
            "Body": new_body.encode("utf-8"),
            "ContentType": "text/html",
        }
        if cache_control:
            put_kwargs["CacheControl"] = cache_control
        s3.put_object(**put_kwargs)
        counts["patch"] += 1
        print(f"patch                 {key}")

    print()
    print(
        f"Summary: patch={counts['patch']} skip={counts['skip']} "
        f"unsupported={counts['unsupported']} invalid={counts['invalid']}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retrofit uploaded slide decks with the Slidecast postMessage nav bridge.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify keys as patch/skip/unsupported without writing to S3.",
    )
    args = parser.parse_args()
    return process(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
