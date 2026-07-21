---
name: slidecast-append
description: Slidecast 뷰어에 html-slide로 만든 HTML 덱을 업로드/수정(버전)/삭제한다. profile2 자격증명으로 S3+DynamoDB에 직접 반영한다. "슬라이드 뷰어에 올려", "slidecast append", "덱 배포"에 트리거.
---

# slidecast-append

방금 만든 self-contained HTML 슬라이드 덱을 Slidecast 갤러리에 반영한다.

## 사전 요구
- `export AWS_PROFILE=profile2 AWS_REGION=us-east-1`
- `export BUCKET_NAME=<cdk-outputs의 BucketName>`
- (선택) `export SLIDECAST_TABLE=SlideDecks`
- playwright chromium: `python3 -m playwright install chromium`

## 사용
- 신규/수정 업로드: `python3 slidecast_append.py deck.html --title "제목" --tags biz,2026`
  - 파일명 슬러그가 기존 덱과 같으면 새 버전으로 추가된다.
- 롤백: `python3 slidecast_append.py --rollback <deckId> <n>`
- 소프트 삭제: `python3 slidecast_append.py --delete <deckId>`
- 영구 삭제: `python3 slidecast_append.py --delete <deckId> --hard`
